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

_components_pattern = re.compile(r'(?<![0-9])(32|16|8)(?![0-9])')

# 非标准分量布局的格式：名称 -> (分量数, 字节宽度, numpy 类型)
# MATRIX3X4_FLOAT：骨骼 3×4 矩阵（12 个 float32 = 48 字节，行主序）
_MATRIX_FORMATS = {
    'MATRIX3X4_FLOAT': (12, 48, numpy.float32),
}

# 打包格式：名称 -> (各分量位宽, 读取用的 numpy 类型)
# R10G10B10A2：32 位打包，R/G/B 各 10 位、A 2 位（常用于法线/颜色），读取时按 uint32 整体读入再解包
_PACKED_FORMATS = {
    'R10G10B10A2_UINT': ((10, 10, 10, 2), numpy.uint32),
}


class DXGIFormat:
    def __init__(self, name: str):
        self.name = name.strip().upper().replace('DXGI_FORMAT_', '')
        self.packed = False

        matrix_fmt = _MATRIX_FORMATS.get(self.name)
        if matrix_fmt is not None:
            self.type_suffix = 'FLOAT'
            self.bit_width = 32
            self.num_values, self.byte_width, self.numpy_type = matrix_fmt
            self.normalize_divisor = None
            return

        packed = _PACKED_FORMATS.get(self.name)
        if packed is not None:
            self.packed = True
            self.packed_bit_widths, self.numpy_type = packed
            self.type_suffix = 'UINT' if self.name.endswith('_UINT') else 'FLOAT'
            self.bit_width = sum(self.packed_bit_widths)
            self.num_values = len(self.packed_bit_widths)
            self.byte_width = (self.bit_width + 7) // 8
            self.normalize_divisor = None
            return

        type_suffix = None
        for suffix in _TYPE_SUFFIXES:
            if self.name.endswith('_' + suffix):
                type_suffix = suffix
                break
        if type_suffix is None:
            raise FormatError(f'无法识别的格式类型: {name}')

        bit_widths = [int(x) for x in _components_pattern.findall(self.name)]
        if not bit_widths:
            raise FormatError(f'格式 {name} 中未找到分量位宽')
        if len(set(bit_widths)) != 1:
            raise FormatError(f'暂不支持混合位宽格式: {name}')

        self.type_suffix = type_suffix
        self.bit_width = bit_widths[0]
        self.num_values = len(bit_widths)
        self.byte_width = self.num_values * (self.bit_width // 8)

        key = (type_suffix, self.bit_width)
        if key not in _NUMPY_TYPES:
            raise FormatError(f'不支持的格式: {name}')

        self.numpy_type = _NUMPY_TYPES[key]
        self.normalize_divisor = _NORMALIZE_DIVISOR.get(key)

    @property
    def is_normalized(self) -> bool:
        return self.normalize_divisor is not None

    def to_float(self, data: numpy.ndarray) -> numpy.ndarray:
        """转换为 float32（对 UNORM/SNORM 做归一化，对打包格式按分量有符号归一化）"""
        if self.normalize_divisor is not None:
            data = data.astype(numpy.float32) / self.normalize_divisor
            return numpy.ascontiguousarray(data, dtype=numpy.float32)
        if self.packed:
            return self.packed_to_float(data)
        return numpy.ascontiguousarray(data, dtype=numpy.float32)

    def packed_to_float(self, data: numpy.ndarray) -> numpy.ndarray:
        """打包格式的 float 转换

        R10G10B10A2_UINT 按 3dmigoto 着色器的 3×10 位八面体法线解码（见 _decode_octahedral_10bit）；
        其他打包格式兜底：10 位分量按补码符号扩展（-512~511）除以 511，其余分量保持原始数值。
        """
        if self.name == 'R10G10B10A2_UINT':
            return _decode_octahedral_10bit(data)
        data = numpy.asarray(data, dtype=numpy.int32)
        columns = []
        for i, width in enumerate(self.packed_bit_widths):
            col = data[:, i]
            if width == 10:
                col = numpy.where(col < 512, col, col - 1024).astype(numpy.float32) / 511.0
            else:
                col = col.astype(numpy.float32)
            columns.append(col)
        return numpy.stack(columns, axis=1)

    def unpack_packed(self, data: numpy.ndarray) -> numpy.ndarray:
        """把打包格式读出的整数值解包为 (n, num_values) 分量数组

        R10G10B10A2 为低位在前：R=bits0-9、G=bits10-19、B=bits20-29、A=bits30-31。
        """
        u = numpy.asarray(data, dtype=numpy.uint32).reshape(-1)
        parts = []
        shift = 0
        for width in self.packed_bit_widths:
            parts.append((u >> shift) & ((1 << width) - 1))
            shift += width
        return numpy.stack(parts, axis=1)


def _decode_octahedral_10bit(data: numpy.ndarray) -> numpy.ndarray:
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
# 常见但命名不规则的格式（B8G8R8A8 = BGRA 排列）、骨骼矩阵与打包格式
for _extra in ('B8G8R8A8_UNORM', 'B8G8R8A8_SNORM', 'MATRIX3X4_FLOAT', 'R10G10B10A2_UINT'):
    try:
        DXGIFormat(_extra)
        if _extra not in SUPPORTED_FORMATS:
            SUPPORTED_FORMATS.append(_extra)
    except FormatError:
        pass

# 各语义推荐使用的常用格式（仅供 UI 提示；不要用于动态枚举排序，否则会因列表重排使已选格式漂移）
SEMANTIC_FORMATS = {
    'INDEX': ('R16_UINT', 'R32_UINT'),
    'POSITION': ('R32G32B32_FLOAT',),
    'NORMAL': ('R32G32B32_FLOAT', 'R8G8B8A8_SNORM', 'R16G16B16A16_SNORM', 'R10G10B10A2_UINT'),
    'TANGENT': ('R32G32B32A32_FLOAT', 'R32G32B32_FLOAT'),
    'TEXCOORD': ('R32G32_FLOAT', 'R16G16_FLOAT', 'R16G16_UNORM', 'R8G8B8A8_UNORM'),
    'COLOR': ('R8G8B8A8_UNORM', 'B8G8R8A8_UNORM', 'R32G32B32A32_FLOAT', 'R16G16B16A16_UNORM'),
    'BLENDINDICES': ('R16_UINT', 'R32_UINT', 'R8_UINT'),
    'BLENDWEIGHTS': ('R32G32B32A32_FLOAT', 'R16G16B16A16_UNORM', 'R32G32B32_FLOAT'),
    'SHAPEKEY_OFFSET': ('R32_UINT',),
    'SHAPEKEY_VERTEXID': ('R32_UINT',),
    'SHAPEKEY_VERTEXOFFSET': ('R16G16B16_FLOAT', 'R32G32B32_FLOAT'),
    'SHAPEKEY': ('R16G16B16_FLOAT', 'R32G32B32_FLOAT'),
    'BONEMATRIX': ('MATRIX3X4_FLOAT',),
}

# 格式下拉的静态枚举项（固定顺序）。必须保持静态：
# Blender 的 EnumProperty 以整数索引存储值，动态重排列表会让已选格式漂移到别的格式。
FORMAT_ENUM_ITEMS = tuple((name, name, '') for name in SUPPORTED_FORMATS)
