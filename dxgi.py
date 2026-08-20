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


class DXGIFormat:
    def __init__(self, name: str):
        self.name = name.strip().upper().replace('DXGI_FORMAT_', '')

        matrix_fmt = _MATRIX_FORMATS.get(self.name)
        if matrix_fmt is not None:
            self.type_suffix = 'FLOAT'
            self.bit_width = 32
            self.num_values, self.byte_width, self.numpy_type = matrix_fmt
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
        """转换为 float32（对 UNORM/SNORM 做归一化）"""
        if self.normalize_divisor is not None:
            data = data.astype(numpy.float32) / self.normalize_divisor
        return numpy.ascontiguousarray(data, dtype=numpy.float32)


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
# 常见但命名不规则的格式（B8G8R8A8 = BGRA 排列）与骨骼矩阵格式
for _extra in ('B8G8R8A8_UNORM', 'B8G8R8A8_SNORM', 'MATRIX3X4_FLOAT'):
    try:
        DXGIFormat(_extra)
        if _extra not in SUPPORTED_FORMATS:
            SUPPORTED_FORMATS.append(_extra)
    except FormatError:
        pass


def format_enum_items():
    return [(name, name, '') for name in SUPPORTED_FORMATS]
