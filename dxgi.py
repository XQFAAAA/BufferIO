"""DXGI 格式解析：按 DirectX 规范解析格式名、通道布局、归一化与 sRGB 解码。

支持的格式来源：
- DXGI 标准格式（R8G8B8A8_UNORM、R16G16_FLOAT、R32G32B32A32_UINT …）；
- 打包格式（R10G10B10A2_UNORM/UINT、B5G6R5_UNORM、B5G5R5A1_UNORM、B4G4R4A4_UNORM、
  R11G11B10_FLOAT、R9G9B9E5_SHAREDEXP）；
- 3dmigoto 社区扩展名（R16G16B16_FLOAT 等 24 位格式、MATRIX3X4_FLOAT）。
"""

import re

import numpy


class FormatError(ValueError):
    pass


_TYPE_SUFFIXES = ('FLOAT', 'UINT', 'SINT', 'UNORM', 'SNORM')

_NUMPY_TYPES = {
    ('FLOAT', 32): numpy.float32,
    ('FLOAT', 16): numpy.float16,
    ('UINT', 32): numpy.uint32,
    ('UINT', 16): numpy.uint16,
    ('UINT', 8): numpy.uint8,
    ('SINT', 32): numpy.int32,
    ('SINT', 16): numpy.int16,
    ('SINT', 8): numpy.int8,
    ('UNORM', 16): numpy.uint16,
    ('UNORM', 8): numpy.uint8,
    ('SNORM', 16): numpy.int16,
    ('SNORM', 8): numpy.int8,
}

_NORMALIZE_DIVISOR = {
    ('UNORM', 16): 65535.0,
    ('UNORM', 8): 255.0,
    ('SNORM', 16): 32767.0,
    ('SNORM', 8): 127.0,
}

# 通道字母 + 位宽，如 R32G32B32_FLOAT -> R32 / G32 / B32
# X 为占位通道（B8G8R8X8 的 X8），读取后丢弃
_CHANNEL_PATTERN = re.compile(r'([RGBAX])(\d+)')

# 特殊布局格式：名称 -> (原始分量数, 字节宽度, 读取用 numpy 类型, 解码器名)
# MATRIX3X4_FLOAT：骨骼 3×4 矩阵（12 个 float32 = 48 字节，行主序）——3dmigoto 扩展，非 DXGI
_SPECIAL_FORMATS = {
    'MATRIX3X4_FLOAT': (12, 48, numpy.float32, 'MATRIX'),
    'R11G11B10_FLOAT': (1, 4, numpy.uint32, 'R11G11B10'),
    'R9G9B9E5_SHAREDEXP': (1, 4, numpy.uint32, 'R9G9B9E5'),
}

# 打包格式：名称 -> (各分量位宽, 各分量归一化除数或 None)
# 位宽从低位到高位排列，与 DXGI 命名顺序一致（R10G10B10A2：R 在低 10 位）
_PACKED_FORMATS = {
    'R10G10B10A2_UINT': ((10, 10, 10, 2), None),
    'R10G10B10A2_UNORM': ((10, 10, 10, 2), (1023.0, 1023.0, 1023.0, 3.0)),
    'B5G6R5_UNORM': ((5, 6, 5), (31.0, 63.0, 31.0)),
    'B5G5R5A1_UNORM': ((5, 5, 5, 1), (31.0, 31.0, 31.0, 1.0)),
    'B4G4R4A4_UNORM': ((4, 4, 4, 4), (15.0, 15.0, 15.0, 15.0)),
}

# 索引缓冲只允许这两种格式（D3D11/D3D12 的 IA 索引格式）
INDEX_FORMATS = ('R16_UINT', 'R32_UINT')


def _split_name(name):
    """拆分格式名：返回 (基础名, 类型后缀, 是否 sRGB)

    _TYPELESS 无具体类型，此处返回 None，由调用方按位宽推断（32 位按 FLOAT，其余按 UNORM）。
    """
    if name.endswith('_UNORM_SRGB'):
        return name[:-len('_UNORM_SRGB')], 'UNORM', True
    if name.endswith('_SRGB'):
        return name[:-len('_SRGB')], 'UNORM', True
    for suffix in _TYPE_SUFFIXES:
        if name.endswith('_' + suffix):
            return name[:-(len(suffix) + 1)], suffix, False
    if name.endswith('_TYPELESS'):
        return name[:-len('_TYPELESS')], None, False
    raise FormatError(f'Unrecognized format type: {name}')


def _parse_channels(base):
    """解析通道字母与位宽（如 R10G10B10A2 -> ('R','G','B','A') + (10,10,10,2)）"""
    matches = _CHANNEL_PATTERN.findall(base)
    if not matches:
        raise FormatError(f'No channel bit widths found in format {base}')
    letters = tuple(letter for letter, _ in matches)
    bits = tuple(int(width) for _, width in matches)
    return letters, bits


def _reorder_indices(letters):
    """按 RGBA 顺序输出，丢弃 X 通道；返回源列索引列表或 None（无需重排）"""
    order = []
    for target in 'RGBA':
        for i, letter in enumerate(letters):
            if letter == target:
                order.append(i)
                break
    index = list(range(len(order)))
    return None if order == index else order


def _srgb_to_linear(values):
    """sRGB -> 线性（硬件在 API 层自动完成，直接读原始字节需手动转换）"""
    values = numpy.clip(values, 0.0, 1.0)
    linear = numpy.where(
        values <= 0.04045,
        values / 12.92,
        numpy.power((values + 0.055) / 1.055, 2.4))
    return linear.astype(numpy.float32)


class DXGIFormat:
    def __init__(self, name: str):
        self.name = name.strip().upper().replace('DXGI_FORMAT_', '')
        self.packed = False
        self.srgb = False
        self.special = None
        self.normalize_divisor = None
        self.packed_divisors = None
        self.channel_letters = ()
        self._reorder = None

        special = _SPECIAL_FORMATS.get(self.name)
        if special is not None:
            self.num_values, self.byte_width, self.numpy_type, self.special = special
            self.bit_width = self.byte_width * 8
            self.type_suffix = 'FLOAT'
            return

        base, suffix, srgb = _split_name(self.name)
        letters, bits = _parse_channels(base)
        self.channel_letters = letters
        self.srgb = srgb

        packed = _PACKED_FORMATS.get(self.name)
        if packed is not None:
            packed_bits, divisors = packed
            self.packed = True
            self.num_values = 1  # 原始数据为单个打包整数，读取后再解包
            self.packed_bit_widths = packed_bits
            self.packed_divisors = divisors
            self.bit_width = sum(packed_bits)
            self.byte_width = (self.bit_width + 7) // 8
            self.numpy_type = (numpy.uint8 if self.byte_width <= 1
                               else numpy.uint16 if self.byte_width <= 2
                               else numpy.uint32)
            self.type_suffix = suffix or 'UNORM'
            self._reorder = _reorder_indices(letters)
            return

        if suffix is None:
            # TYPELESS：按位宽推断（32 位按浮点，8/16 位按归一化无符号）
            suffix = 'FLOAT' if len(set(bits)) == 1 and bits[0] == 32 else 'UNORM'
        if len(set(bits)) != 1:
            raise FormatError(f'Mixed bit-width format not supported: {name}')
        self.type_suffix = suffix
        self.bit_width = bits[0]
        self.num_values = len(bits)
        self.byte_width = self.num_values * (self.bit_width // 8)

        key = (suffix, self.bit_width)
        if key not in _NUMPY_TYPES:
            raise FormatError(f'Unsupported format: {name}')

        self.numpy_type = _NUMPY_TYPES[key]
        self.normalize_divisor = _NORMALIZE_DIVISOR.get(key)
        self._reorder = _reorder_indices(letters)

    @property
    def is_normalized(self) -> bool:
        return self.normalize_divisor is not None or self.packed_divisors is not None

    def to_float(self, data: numpy.ndarray) -> numpy.ndarray:
        """转换为 float32：按规范归一化、重排通道、sRGB 转线性

        打包格式的入参须是 buffer_io 解包后的分量列（见 unpack_packed）；
        特殊格式（R11G11B10 / R9G9B9E5 / MATRIX3X4）直接接收原始整数行。
        """
        if self.special == 'R11G11B10':
            return _decode_r11g11b10(data)
        if self.special == 'R9G9B9E5':
            return _decode_r9g9b9e5(data)
        if self.packed:
            values = data.astype(numpy.float32)
            if self.packed_divisors is not None:
                values = values / numpy.array(self.packed_divisors,
                                              dtype=numpy.float32)
        elif self.normalize_divisor is not None:
            values = data.astype(numpy.float32) / self.normalize_divisor
            if self.type_suffix == 'SNORM':
                # -32768/32767 会略小于 -1，按规范截断
                numpy.clip(values, -1.0, 1.0, out=values)
        else:
            values = numpy.ascontiguousarray(data, dtype=numpy.float32)

        if self._reorder is not None:
            values = values[:, self._reorder]
        if self.srgb:
            values = _srgb_to_linear(values)
        return numpy.ascontiguousarray(values, dtype=numpy.float32)

    def unpack_packed(self, data: numpy.ndarray) -> numpy.ndarray:
        """把打包格式读出的整数值解包为 (n, num_components) 分量数组

        低位在前：R10G10B10A2 为 R=bits0-9、G=bits10-19、B=bits20-29、A=bits30-31。
        """
        packed_bits = self.packed_bit_widths
        u = numpy.asarray(data, dtype=numpy.uint32).reshape(-1)
        parts = []
        shift = 0
        for width in packed_bits:
            parts.append((u >> shift) & ((1 << width) - 1))
            shift += width
        return numpy.stack(parts, axis=1)


def decode_octahedral_10bit(data: numpy.ndarray) -> numpy.ndarray:
    """把 R10G10B10A2 打包分量（10+10+10+2）解码为八面体单位法线 (n,3)

    参考 3dmigoto 着色器（vs 中 v2.x 的位运算）：
      1. 前两个 10 位分量按补码符号扩展为 -512~511（raw>=512 ? raw-1024 : raw）；
      2. 除以 511 得八面体坐标 (X, Y)；
      3. 八面体解码：Z = 1-|X|-|Y|，Z<0 时折叠 X=(1-|Y|)*sign(X)、Y=(1-|X|)*sign(Y)；
      4. 归一化为单位法线。
    第三个 10 位分量与第 31 位符号位用于切线帧，法线仅用前两个分量。
    """
    c = numpy.asarray(data, dtype=numpy.int32)
    sx = numpy.where(c[:, 0] < 512, c[:, 0], c[:, 0] - 1024).astype(numpy.float32)
    sy = numpy.where(c[:, 1] < 512, c[:, 1], c[:, 1] - 1024).astype(numpy.float32)
    x = sx / 511.0
    y = sy / 511.0
    z = 1.0 - numpy.abs(x) - numpy.abs(y)
    neg = z < 0.0
    sign_x = numpy.where(sx >= 0.0, 1.0, -1.0)
    sign_y = numpy.where(sy >= 0.0, 1.0, -1.0)
    xn = numpy.where(neg, (1.0 - numpy.abs(y)) * sign_x, x)
    yn = numpy.where(neg, (1.0 - numpy.abs(x)) * sign_y, y)
    normal = numpy.stack([xn, yn, z], axis=1)
    length = numpy.sqrt((normal * normal).sum(axis=1, keepdims=True))
    return (normal / numpy.maximum(length, 1e-12)).astype(numpy.float32)


def _decode_r11g11b10(data: numpy.ndarray) -> numpy.ndarray:
    """R11G11B10_FLOAT：无符号浮点（R/G 各 11 位：5 位指数 + 6 位尾数；B 10 位：5+5）"""
    u = numpy.asarray(data, dtype=numpy.uint32).reshape(-1)
    columns = []
    for shift, mantissa_bits in ((0, 6), (11, 6), (22, 5)):
        mantissa = ((u >> shift) & ((1 << mantissa_bits) - 1)).astype(numpy.float32)
        exponent = ((u >> (shift + mantissa_bits)) & 0x1F).astype(numpy.int32)
        fraction = mantissa / float(1 << mantissa_bits)
        scale = numpy.exp2(numpy.where(exponent == 0, -14.0,
                                       (exponent - 15).astype(numpy.float32)))
        value = numpy.where(exponent == 0, fraction, 1.0 + fraction) * scale
        columns.append(value)
    return numpy.stack(columns, axis=1).astype(numpy.float32)


def _decode_r9g9b9e5(data: numpy.ndarray) -> numpy.ndarray:
    """R9G9B9E5_SHAREDEXP：3 个 9 位尾数共享 5 位指数，值 = 尾数 × 2^(指数-24)"""
    u = numpy.asarray(data, dtype=numpy.uint32).reshape(-1)
    exponent = ((u >> 27) & 0x1F).astype(numpy.float32)
    scale = numpy.exp2(exponent - 24.0)
    mantissas = [
        (u & 0x1FF).astype(numpy.float32),
        ((u >> 9) & 0x1FF).astype(numpy.float32),
        ((u >> 18) & 0x1FF).astype(numpy.float32),
    ]
    return numpy.stack([m * scale for m in mantissas], axis=1).astype(numpy.float32)


def _build_format_items():
    items = []
    for bits in ('32', '16', '8'):
        for suffix in _TYPE_SUFFIXES:
            if suffix == 'FLOAT' and bits == '8':
                continue
            for channels in ('RGBA', 'RGB', 'RG', 'R'):
                name = ''.join(c + bits for c in channels) + '_' + suffix
                try:
                    DXGIFormat(name)
                except FormatError:
                    continue
                items.append(name)
    return items


SUPPORTED_FORMATS = _build_format_items()
# 非均匀分量的真实 DXGI 格式、sRGB / TYPELESS 变体与 3dmigoto 扩展。
# 只追加在末尾：已保存的枚举值按标识符（名称）存储，追加不会影响旧数据。
_EXTRA_FORMATS = (
    'B8G8R8A8_UNORM', 'B8G8R8A8_SNORM', 'B8G8R8X8_UNORM',
    'A8_UNORM',
    'R10G10B10A2_UNORM', 'R10G10B10A2_UINT',
    'R11G11B10_FLOAT', 'R9G9B9E5_SHAREDEXP',
    'B5G6R5_UNORM', 'B5G5R5A1_UNORM', 'B4G4R4A4_UNORM',
    'R8G8B8A8_UNORM_SRGB', 'B8G8R8A8_UNORM_SRGB',
    'R8G8B8A8_TYPELESS', 'B8G8R8A8_TYPELESS',
    'R16G16B16A16_TYPELESS', 'R32G32B32A32_TYPELESS', 'R32G32B32_TYPELESS',
    'MATRIX3X4_FLOAT',
)
for _extra in _EXTRA_FORMATS:
    try:
        DXGIFormat(_extra)
        if _extra not in SUPPORTED_FORMATS:
            SUPPORTED_FORMATS.append(_extra)
    except FormatError:
        pass

# 各语义推荐使用的常用格式（仅供 UI 提示；不要用于动态枚举排序）
SEMANTIC_FORMATS = {
    'INDEX': ('R16_UINT', 'R32_UINT'),
    'POSITION': ('R32G32B32_FLOAT',),
    'NORMAL': ('R32G32B32_FLOAT', 'R8G8B8A8_SNORM', 'R16G16B16A16_SNORM',
               'R10G10B10A2_UNORM', 'R10G10B10A2_UINT'),
    'TANGENT': ('R32G32B32A32_FLOAT', 'R32G32B32_FLOAT', 'R10G10B10A2_UNORM'),
    'TEXCOORD': ('R32G32_FLOAT', 'R16G16_FLOAT', 'R16G16_UNORM', 'R8G8B8A8_UNORM'),
    'COLOR': ('R8G8B8A8_UNORM', 'B8G8R8A8_UNORM', 'R32G32B32A32_FLOAT',
              'R16G16B16A16_UNORM', 'R10G10B10A2_UNORM'),
    'BLENDINDICES': ('R16_UINT', 'R32_UINT', 'R8_UINT'),
    'BLENDWEIGHTS': ('R32G32B32A32_FLOAT', 'R16G16B16A16_UNORM', 'R32G32B32_FLOAT'),
    'SHAPEKEY_OFFSET': ('R32_UINT',),
    'SHAPEKEY_VERTEXID': ('R32_UINT',),
    'SHAPEKEY_VERTEXOFFSET': ('R16G16B16_FLOAT', 'R32G32B32_FLOAT'),
    'SHAPEKEY': ('R16G16B16_FLOAT', 'R32G32B32_FLOAT'),
    'BONEMATRIX': ('MATRIX3X4_FLOAT',),
}

# 格式下拉的静态枚举项（固定顺序）
# 静态 items 在 .blend 中按标识符（名称）存储，因此可安全地追加/重排；
# 只有用 items 回调（dynamic enum）时才按整数索引存储、重排会导致漂移。
FORMAT_ENUM_ITEMS = tuple((name, name, '') for name in SUPPORTED_FORMATS)
