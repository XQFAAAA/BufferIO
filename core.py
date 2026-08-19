"""BufferIO 核心逻辑：条目校验、顶点数组收集、网格对象构建与链接。"""

from pathlib import Path

import numpy
import bpy
from bpy_extras.io_utils import axis_conversion

from . import buffer_io
from . import dxgi
from . import fmt_parser
from .constants import FLOAT_SEMANTICS


def validate_entries(entries):
    """校验列表项的步长与偏移，设置每项 warning 状态（仅提示不影响导入）

    0 正常 /
    1 红(ERROR)：同文件步长不一致；格式越界（offset+宽度>步长）；或 SemanticName/SemanticIndex 冲突 /
    2 黄(QUESTION)：相邻项偏移差 != 前一项格式字节宽度（布局不连续，优先于越界 ERROR）

    返回 dict：{'red': int, 'yellow': int, 'missing': [str, ...]}
    missing 为缺失的必需语义（INDEX / POSITION）
    """
    # 先清空所有项的旧警告状态，避免上次校验残留
    for entry in entries:
        entry.warning = 0

    # 按文件来源分组
    groups = {}
    for entry in entries:
        fp = getattr(entry, 'filepath', '') or getattr(entry, 'source_file', '')
        if not fp:
            continue
        groups.setdefault(fp, []).append(entry)

    for fp, group in groups.items():
        # 规则1：同文件非索引项步长应一致，否则全组 ERROR
        # （INDEX 为平铺数据，stride 无意义，不参与比较）
        strides = {e.stride for e in group if e.semantic != 'INDEX'}
        if len(strides) > 1:
            for e in group:
                e.warning = 1
            continue

        # 索引为平铺数据（offset 是文件偏移），不参与字节布局校验
        non_index = [e for e in group if e.semantic != 'INDEX']

        # 组内无非索引项（只有 INDEX）或无有效步长，跳过字节布局校验
        if not non_index or not strides:
            continue

        stride = next(iter(strides))

        def width(e):
            try:
                return dxgi.DXGIFormat(e.format).byte_width
            except dxgi.FormatError:
                return -1

        # 规则3：相邻项偏移差应等于前一项格式字节宽度（布局连续），
        # 不连续则前项与后项同时标 QUESTION；最后一项与步长的间隙不匹配标自身
        ordered = sorted(non_index, key=lambda e: e.offset)
        for i, e in enumerate(ordered):
            if i + 1 < len(ordered):
                gap = ordered[i + 1].offset - e.offset
            else:
                gap = stride - e.offset
            if stride > 0 and gap != width(e):
                e.warning = 2
                if i + 1 < len(ordered):
                    ordered[i + 1].warning = 2

        # 规则4：SemanticName/SemanticIndex 冲突——同一原始语义被重复映射标 ERROR
        # （不覆盖已标 QUESTION 的项）
        seen = {}
        for e in non_index:
            if not getattr(e, 'enabled', True):
                continue
            if getattr(e, 'semantic', 'SKIP') == 'SKIP':
                continue
            name = getattr(e, 'semantic_name', '') or e.semantic
            key = (name, e.semantic_index)
            if key in seen:
                if e.warning != 2:
                    e.warning = 1
                if seen[key].warning != 2:
                    seen[key].warning = 1
            else:
                seen[key] = e

        # 规则2：格式越界（offset+宽度>步长）标 ERROR，
        # 但已被 QUESTION（布局不连续）标记的项保持 QUESTION
        for e in non_index:
            if stride > 0 and e.offset + width(e) > stride and e.warning != 2:
                e.warning = 1

    # 规则5：检查必需语义是否存在（INDEX 与 POSITION）
    missing = []
    enabled_sem = {getattr(e, 'semantic', None) for e in entries if getattr(e, 'enabled', True)}
    if 'INDEX' not in enabled_sem:
        missing.append('INDEX')
    if 'POSITION' not in enabled_sem:
        missing.append('POSITION')

    red = sum(1 for e in entries if e.warning == 1)
    yellow = sum(1 for e in entries if e.warning == 2)
    return {'red': red, 'yellow': yellow, 'missing': missing}


def _trim_shapekey_data(offsets, vertex_ids, vertex_offsets):
    """截断形态键数据：ShapeKeyOffset 不严格递增（与上一个相同或更小）时，
    说明其后为无效数据（如读取到 15406,15568,15568），放弃该位置及之后全部数据。

    返回 (offsets, vertex_ids, vertex_offsets) 截断后的三元组。
    """
    offsets = numpy.asarray(offsets, dtype=numpy.int64)
    # 找到第一个不递增的位置：offsets[i] <= offsets[i-1]
    if len(offsets) > 1:
        diffs = numpy.diff(offsets)
        bad = numpy.where(diffs <= 0)[0]
        if len(bad):
            cut = int(bad[0]) + 1  # 截断到第 cut 个边界
            offsets = offsets[:cut]
            # vertex_ids/vertex_offsets 只保留到最后一个有效边界之前
            limit = int(offsets[-1]) if len(offsets) else 0
            vertex_ids = numpy.asarray(vertex_ids)[:limit]
            vertex_offsets = numpy.asarray(vertex_offsets)[:limit]
    return offsets, vertex_ids, vertex_offsets


def _read_index_entry(entry, filepath):
    """读取 INDEX 项的面数据。

    优先级：文件路径+first/count -> 文件路径（自动分辨类型）-> ib txt。
    first_vertex 为起始偏移，vertex_count 为限制数量（0 = 不限制）。
    """
    first = getattr(entry, 'first_vertex', 0)
    count = getattr(entry, 'vertex_count', 0)
    limit = getattr(entry, 'count', 0)
    # 优先级1：文件路径 + first/count（设了偏移或数量限制）
    if filepath and (first > 0 or count > 0):
        return buffer_io.read_indices(
            filepath, entry.format,
            offset=getattr(entry, 'offset', 0),
            first=first, count=count, limit=limit)
    # 优先级2：仅有文件路径，自动分辨类型
    if filepath:
        # txt 直接解析（头部含 first/vertex 与文本索引）
        if Path(filepath).suffix.lower() == '.txt':
            return buffer_io.read_indices_from_ib_txt(filepath)
        # buf：offset 为文件起始字节偏移，平铺读取
        return buffer_io.read_indices(
            filepath, entry.format, offset=getattr(entry, 'offset', 0), limit=limit)
    # 优先级3：仅 ib txt 路径
    if getattr(entry, 'ib_txt', ''):
        ib_txt = entry.ib_txt
        if not Path(ib_txt).is_file():
            raise buffer_io.BufferIOError(f'IB txt 不存在: {ib_txt}')
        return buffer_io.read_indices_from_ib_txt(ib_txt)
    raise buffer_io.BufferIOError(f'{entry.semantic} 未指定文件路径')


def _read_vertex_entry(entry, filepath):
    """读取顶点属性条目数组，返回 (array, fmt)"""
    # 顶点属性：offset / byte_offset 均为元素在步长内的字节偏移
    elem_offset = getattr(entry, 'byte_offset', getattr(entry, 'offset', 0))
    return buffer_io.read_buffer(
        filepath, entry.format, stride=entry.stride,
        offset=0, elem_offset=elem_offset,
        limit=getattr(entry, 'count', 0))


def collect_vertex_arrays(entries):
    """读取条目数据并按语义分组

    返回 (faces, vertex_arrays)
    vertex_arrays 的键为 (semantic, semantic_index)
    """
    faces = None
    arrays = {}

    for entry in entries:
        if not getattr(entry, 'enabled', True):
            continue
        filepath = getattr(entry, 'filepath', '') or getattr(entry, 'source_file', '')

        if entry.semantic == 'INDEX':
            faces = _read_index_entry(entry, filepath)
            continue

        if not filepath:
            raise buffer_io.BufferIOError(f'{entry.semantic} 未指定文件路径')
        array, fmt = _read_vertex_entry(entry, filepath)

        # 目标索引决定 UV/颜色等属性的编号（如 TEXCOORD 0-3）
        key = (entry.semantic, getattr(entry, 'index', entry.semantic_index))
        if entry.semantic in FLOAT_SEMANTICS:
            arrays[key] = fmt.to_float(array)
        else:
            arrays[key] = numpy.ascontiguousarray(array)

    return faces, arrays


def build_and_link(context, name, faces, arrays, flip_winding, flip_texcoord_v,
                   scale=1.0, mirror_x=False, axis_forward='-Y', axis_up='Z'):
    # 未提供面索引时需用原始顶点数生成顺序三角形
    positions_orig = arrays.get(('POSITION', 0))
    if positions_orig is None:
        # 允许使用任意索引的 POSITION
        for (semantic, _), data in arrays.items():
            if semantic == 'POSITION':
                positions_orig = data
                break
    if positions_orig is None:
        raise buffer_io.BufferIOError('缺少顶点位置（POSITION）数据')

    if faces is None:
        if len(positions_orig) % 3 != 0:
            raise buffer_io.BufferIOError(
                f'未提供面索引且顶点数 {len(positions_orig)} 不是 3 的倍数')
        faces = numpy.arange(len(positions_orig), dtype=numpy.uint32).reshape(-1, 3)

    # 形态键数据是分段索引（非 per-vertex 属性），须在顶点压缩前取出，
    # 避免被 compact_vertices 当作顶点数组切片。
    # 支持按索引分组：如 SHAPEKEY_OFFSET/ID/OFFSET 索引 0 一组、索引 1 一组...
    sk_groups = []
    for key in [k for k in list(arrays.keys()) if k[0] == 'SHAPEKEY_OFFSET']:
        idx = key[1]
        sk_offsets = arrays.pop(key, None)
        sk_ids = arrays.pop(('SHAPEKEY_VERTEXID', idx), None)
        sk_vecs = arrays.pop(('SHAPEKEY_VERTEXOFFSET', idx), None)
        if sk_offsets is not None and sk_ids is not None and sk_vecs is not None:
            # ShapeKeyOffset 出现不递增（<= 上一个）时，其后为无效数据，截断
            sk_groups.append(_trim_shapekey_data(sk_offsets, sk_ids, sk_vecs))
    shape_keys = sk_groups if sk_groups else None

    # 顶点压缩会对所有数组做 v_min 重基与切片，
    # 之后所有属性必须从压缩后的 arrays 中重新取，否则与 faces 索引不一致
    faces, arrays, v_min = buffer_io.compact_vertices(faces, arrays)

    # 逐顶点形态键（SHAPEKEY 索引即 Deform 编号）：随顶点压缩一致切片，
    # 每个 (SHAPEKEY, i) 数组是第 i 个形态键各顶点的位移向量
    shape_key_arrays = {
        index: data for (sem, index), data in arrays.items() if sem == 'SHAPEKEY'
    }

    def get(semantic):
        return {index: data for (sem, index), data in arrays.items() if sem == semantic}

    def get_first(semantic):
        values = get(semantic)
        return values.get(0) if values else None

    positions = get_first('POSITION')
    if positions is None:
        raise buffer_io.BufferIOError('缺少顶点位置（POSITION）数据')

    obj = buffer_io.build_object(
        name, faces, positions,
        normals=get_first('NORMAL'),
        tangents=get_first('TANGENT'),
        uvs=get('TEXCOORD'),
        colors=get('COLOR'),
        blend_indices=get('BLENDINDICES'),
        blend_weights=get('BLENDWEIGHTS'),
        shape_keys=shape_keys,
        shape_key_arrays=shape_key_arrays or None,
        shape_key_offset=v_min,
        flip_winding=flip_winding,
        flip_texcoord_v=flip_texcoord_v,
        scale=scale,
        mirror_x=mirror_x,
    )

    # 坐标系变换：将源坐标轴映射到 Blender 的 -Y 前 / Z 上
    # （显式指定目标轴，使默认 -Y/Z 返回单位阵，保持原有行为不变）
    obj.matrix_world = axis_conversion(
        from_forward=axis_forward, from_up=axis_up,
        to_forward='-Y', to_up='Z').to_4x4()

    collection = context.collection or context.scene.collection
    collection.objects.link(obj)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj
