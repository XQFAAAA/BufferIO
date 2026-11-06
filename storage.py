"""BufferIO 底层二进制读取：mmap 缓存、属性 / 索引读取与顶点压缩。

这里只依赖 numpy / 标准库，不涉及 Blender，便于单独验证；
网格与骨架的构建留在 buffer_io.py。
"""

import mmap
import os
from collections import OrderedDict
from pathlib import Path

import numpy

from .dxgi import DXGIFormat


class BufferIOError(ValueError):
    pass


# 同一个 .buf 通常被多个元素重复读取（POSITION / NORMAL / TEXCOORD 共享 vb0.buf）。
# 用 mmap 缓存整个文件：不必每次都从磁盘重读，也不占用等量物理内存。
# 按 (路径, 大小, 修改时间) 校验；超出上限后按最久未用淘汰旧映射。
_CACHE_MAX_TOTAL = 1024 * 1024 * 1024
_maps = OrderedDict()
_maps_bytes = 0


def _file_map(filepath):
    """取文件的只读 mmap（带 mtime / 大小校验的进程级缓存）"""
    global _maps_bytes
    path = Path(filepath)
    try:
        stat = path.stat()
    except OSError as exc:
        raise BufferIOError(f'Cannot access file {path.name}: {exc}') from exc

    key = (os.path.abspath(str(path)), stat.st_size, stat.st_mtime_ns)
    mapping = _maps.get(key)
    if mapping is not None:
        _maps.move_to_end(key)
        return mapping

    if stat.st_size == 0:
        raise BufferIOError(f'File is empty: {path.name}')
    with open(path, 'rb') as handle:
        try:
            mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        except OSError as exc:
            raise BufferIOError(f'Cannot read file {path.name}: {exc}') from exc

    _maps[key] = mapping
    _maps_bytes += stat.st_size
    while _maps_bytes > _CACHE_MAX_TOTAL and len(_maps) > 1:
        _, old = _maps.popitem(last=False)
        _maps_bytes -= len(old)
        try:
            old.close()
        except BufferError:
            pass  # 仍有 numpy 视图引用，交给 GC 回收
    return mapping


def clear_cache():
    """释放全部文件映射（修改文件后需要强制重读时使用）"""
    global _maps_bytes
    for mapping in _maps.values():
        try:
            mapping.close()
        except BufferError:
            pass
    _maps.clear()
    _maps_bytes = 0


def read_buffer(filepath, format_name, stride=0, offset=0, elem_offset=0, limit=0):
    """从二进制文件读取单个属性的数据数组

    filepath:   数据文件路径
    format_name: DXGI 格式名（如 R32G32B32_FLOAT）
    stride:     每元素字节步长，0 = 紧凑（= 格式字节宽度）
    offset:     文件起始字节偏移
    elem_offset: 属性在元素内的字节偏移（fmt 模式的 AlignedByteOffset）
    limit:      读取元素数量上限，0 = 不限制（缓冲末尾可能存在无效数据）
    """
    fmt = DXGIFormat(format_name)
    if stride == 0:
        stride = fmt.byte_width
    if elem_offset + fmt.byte_width > stride:
        raise BufferIOError(
            f'Format {format_name} ({fmt.byte_width} bytes) at offset {elem_offset} exceeds stride {stride}')

    data = _file_map(filepath)
    size = len(data)
    start = offset + elem_offset
    if start > size:
        raise BufferIOError(f'Offset {start} is beyond the file size {size}')
    count = (size - offset) // stride
    if count <= 0:
        raise BufferIOError(f'No readable data in file {Path(filepath).name}')
    if limit > 0:
        count = min(count, limit)

    # 用带步长的 ndarray 视图直接定位数据（避免结构化 dtype 的额外中间层）
    item_size = numpy.dtype(fmt.numpy_type).itemsize
    if fmt.num_values > 1:
        view = numpy.ndarray((count, fmt.num_values), dtype=fmt.numpy_type,
                             buffer=data, offset=start,
                             strides=(stride, item_size))
    else:
        view = numpy.ndarray((count,), dtype=fmt.numpy_type,
                             buffer=data, offset=start,
                             strides=(stride,))

    # 视图指向只读映射，后续还要做缩放 / 镜像等原地变换，复制为可写
    array = numpy.array(view, copy=True)
    if fmt.packed:
        array = fmt.unpack_packed(array)
    return array, fmt


def read_indices(filepath, format_name, stride=0, offset=0, first=0, count=0, limit=0):
    """读取索引缓冲并重组为三角形面

    first:  起始索引偏移；count: 索引数量（0 = 不限制）
    limit:  读取元素数量上限，0 = 不限制（在切片前生效）
    """
    array, _fmt = read_buffer(filepath, format_name, stride=stride,
                              offset=offset, limit=limit)
    # 索引统一为 int32（Blender 的 loop.vertex_index 即 int32，且省一半内存）
    indices = numpy.ascontiguousarray(array.reshape(-1), dtype=numpy.int32)

    if count > 0 and first + count <= len(indices):
        indices = indices[first:first + count]
    elif first > 0:
        indices = indices[first:]

    if len(indices) % 3 != 0:
        raise BufferIOError(f'Index count {len(indices)} is not a multiple of 3')

    return indices.reshape(-1, 3)


def read_indices_from_ib_txt(filepath):
    """从 3dmigoto FrameAnalysis 的 ib txt 直接解析索引

    txt 头部含 format / first index / index count 等，
    头部之后每行 3 个索引，是已按 first/count 切片好的数据。
    无需依赖 .buf 文件，也无需手动指定格式与偏移。
    """
    from .fmt_parser import parse_fmt_text

    filepath = Path(filepath)
    text = filepath.read_text(encoding='utf-8', errors='replace')
    parse_fmt_text(text)  # 校验拓扑为 trianglelist

    # 头部各行均含冒号，数据行全部为索引数字
    lines = text.splitlines()
    data_start = next(
        (i for i, raw in enumerate(lines) if ':' not in raw.strip()),
        len(lines))
    # 数据区一次性分词后交给 numpy 转换，避免逐行 Python 循环（百万索引时差异明显）
    tokens = '\n'.join(lines[data_start:]).split()
    if not tokens:
        raise BufferIOError(f'No index data in ib txt: {filepath.name}')

    indices = numpy.array(tokens, dtype=numpy.int32)
    if len(indices) % 3 != 0:
        raise BufferIOError(f'Index count {len(indices)} is not a multiple of 3')
    return indices.reshape(-1, 3)


def compact_vertices(faces, arrays):
    """去除未被索引引用的顶点，并把索引重排为连续编号

    返回 (faces, arrays, vertex_map)：
      vertex_map 为 int64 数组，vertex_map[旧顶点号] = 新顶点号，
      未被引用的顶点为 -1；不需要压缩时返回 None（调用方据此跳过重映射）。
    """
    if faces is None or len(faces) == 0:
        return faces, arrays, None

    used = numpy.unique(numpy.asarray(faces).reshape(-1))
    if used.size == 0:
        return faces, arrays, None

    count = int(used[-1]) + 1
    for key, array in arrays.items():
        if array is not None and len(array) < count:
            raise BufferIOError(
                f'Insufficient vertex data: max index is {count - 1}, '
                f'but {key} only has {len(array)} vertices')

    # 引用恰好覆盖 0..max 且各数组长度匹配时无需重排
    contiguous_ids = used[0] == 0 and used.size == count
    same_length = all(len(a) == count for a in arrays.values() if a is not None)
    if contiguous_ids and same_length:
        return faces, arrays, None

    vertex_map = numpy.full(count, -1, dtype=numpy.int64)
    vertex_map[used] = numpy.arange(used.size, dtype=numpy.int64)

    new_faces = numpy.ascontiguousarray(vertex_map[faces], dtype=numpy.int32)
    new_arrays = {
        key: None if array is None else numpy.ascontiguousarray(array[used])
        for key, array in arrays.items()
    }
    return new_faces, new_arrays, vertex_map
