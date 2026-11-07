"""BufferIO 核心逻辑：索引/形态键数据读取、网格对象构建与链接。"""

from pathlib import Path

import numpy
import bpy
from bpy_extras.io_utils import axis_conversion

from . import buffer_io


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
    first_index 为起始偏移，index_count 为限制数量（0 = 不限制）。
    """
    first = getattr(entry, 'first_index', 0)
    count = getattr(entry, 'index_count', 0)
    limit = getattr(entry, 'count', 0)
    # 数据在缓冲文件中的起始字节偏移；旧数据没有 byte_offset 时回退到 offset
    file_offset = getattr(entry, 'byte_offset', 0) or getattr(entry, 'offset', 0)
    # 优先级1：文件路径 + first/count（设了偏移或数量限制）
    if filepath and (first > 0 or count > 0):
        return buffer_io.read_indices(
            filepath, entry.format,
            offset=file_offset,
            first=first, count=count, limit=limit)
    # 优先级2：仅有文件路径，自动分辨类型
    if filepath:
        # txt 直接解析（头部含 first/vertex 与文本索引）
        if Path(filepath).suffix.lower() == '.txt':
            return buffer_io.read_indices_from_ib_txt(filepath)
        # buf：offset 为文件起始字节偏移，平铺读取
        return buffer_io.read_indices(
            filepath, entry.format, offset=file_offset, limit=limit)
    # 优先级3：仅 ib txt 路径
    if getattr(entry, 'ib_txt', ''):
        ib_txt = entry.ib_txt
        if not Path(ib_txt).is_file():
            raise buffer_io.BufferIOError(f'IB txt not found: {ib_txt}')
        return buffer_io.read_indices_from_ib_txt(ib_txt)
    raise buffer_io.BufferIOError(f'{entry.semantic}: no file path specified')


def build_and_link(context, name, faces, arrays, flip_winding, flip_texcoord_v,
                   scale=1.0, mirror_x=False, axis_forward='-Y', axis_up='Z',
                   armature_name=None, shape_keys=None, bone_matrices=None,
                   vertex_map=None):
    # 数组内容只读使用，但下面会从字典中取出形态键 / 骨骼矩阵数据，
    # 浅复制字典即可，避免改动多个 Import 节点共享的 MeshData.arrays
    arrays = dict(arrays)

    # 未提供面索引时需用原始顶点数生成顺序三角形
    positions_orig = arrays.get(('POSITION', 0))
    if positions_orig is None:
        # 允许使用任意索引的 POSITION
        for (semantic, _), data in arrays.items():
            if semantic == 'POSITION':
                positions_orig = data
                break
    if positions_orig is None:
        raise buffer_io.BufferIOError('Missing vertex position (POSITION) data')

    if faces is None:
        if len(positions_orig) % 3 != 0:
            raise buffer_io.BufferIOError(
                f'No faces provided and vertex count {len(positions_orig)} is not a multiple of 3')
        faces = numpy.arange(len(positions_orig), dtype=numpy.uint32).reshape(-1, 3)

    # 形态键数据是分段索引（非 per-vertex 属性），须在顶点压缩前取出，
    # 避免被 compact_vertices 当作顶点数组切片。
    # 支持按索引分组：如 SHAPEKEY_OFFSET/ID/OFFSET 索引 0 一组、索引 1 一组...
    # 节点式导入可直接传入已分组的 shape_keys，跳过从 arrays 提取。
    sk_groups = []
    if shape_keys is not None:
        sk_groups = [_trim_shapekey_data(*group) for group in shape_keys]
    else:
        for key in [k for k in list(arrays.keys()) if k[0] == 'SHAPEKEY_OFFSET']:
            idx = key[1]
            sk_offsets = arrays.pop(key, None)
            sk_ids = arrays.pop(('SHAPEKEY_VERTEXID', idx), None)
            sk_vecs = arrays.pop(('SHAPEKEY_VERTEXOFFSET', idx), None)
            if sk_offsets is not None and sk_ids is not None and sk_vecs is not None:
                # ShapeKeyOffset 出现不递增（<= 上一个）时，其后为无效数据，截断
                sk_groups.append(_trim_shapekey_data(sk_offsets, sk_ids, sk_vecs))
    shape_keys = sk_groups if sk_groups else None

    # 骨骼矩阵为按骨骼组织的分段数据（非逐顶点），须在顶点压缩前取出
    # 取第一个 BONEMATRIX 条目（多组骨骼暂只支持一组）；节点式导入可直接传入
    if bone_matrices is not None:
        bone_matrices = numpy.ascontiguousarray(bone_matrices).reshape(-1, 3, 4)
    else:
        for key in [k for k in list(arrays.keys()) if k[0] == 'BONEMATRIX']:
            data = arrays.pop(key, None)
            if data is not None:
                bone_matrices = numpy.ascontiguousarray(data).reshape(-1, 3, 4)
                break

    # 顶点压缩会对所有数组做重排与切片，之后所有属性必须从压缩后的 arrays 中重新取。
    # 节点式导入已在 Mesh Assemble 中压缩过，直接用它的映射表，避免重复处理。
    if vertex_map is None:
        faces, arrays, vertex_map = buffer_io.compact_vertices(faces, arrays)

    # 逐顶点形态键（SHAPEKEY 索引即 Deform 编号）：随顶点压缩一致切片，
    # 每个 (SHAPEKEY, i) 数组是第 i 个形态键各顶点的位移向量
    shape_key_arrays = {
        index: data for (sem, index), data in arrays.items() if sem == 'SHAPEKEY'
    }

    def get(semantic):
        return {index: data for (sem, index), data in arrays.items() if sem == semantic}

    def get_first(semantic):
        # 取该语义目标索引最小的数组，而不是只认索引 0：
        # NORMAL/TANGENT 的目标索引常被设为源语义索引（如 wuwa 预设 NORMAL=2、TANGENT=1），
        # 之前只查索引 0 会把法线/切线静默丢弃，导入后网格仍用自动法线
        values = get(semantic)
        return values[min(values)] if values else None

    positions = get_first('POSITION')
    if positions is None:
        raise buffer_io.BufferIOError('Missing vertex position (POSITION) data')

    # 坐标系变换：将源坐标轴映射到 Blender 的 -Y 前 / Z 上，
    # 作用于顶点/法线/形态键与骨骼矩阵数据本身，对象保持无变换
    conversion = axis_conversion(
        from_forward=axis_forward, from_up=axis_up,
        to_forward='-Y', to_up='Z').to_4x4()

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
        vertex_map=vertex_map,
        flip_winding=flip_winding,
        flip_texcoord_v=flip_texcoord_v,
        scale=scale,
        mirror_x=mirror_x,
        conversion=conversion,
    )

    collection = context.collection or context.scene.collection
    collection.objects.link(obj)

    # 自动创建骨架：骨骼矩阵 + 顶点组权重 -> Armature 蒙皮
    if bone_matrices is not None and len(bone_matrices):
        # 只导入 BLENDINDICES 中实际引用到的骨骼，跳过缓冲中的无效/未使用槽位
        used_bones = set()
        for _, data in get('BLENDINDICES').items():
            used_bones |= buffer_io._collect_used_bone_indices(data)
        arm_obj = buffer_io.build_armature(
            armature_name or f'{name}_Armature', bone_matrices,
            scale=scale, mirror_x=mirror_x, conversion=conversion,
            collection=collection, indices=used_bones or None)
        modifier = obj.modifiers.new(name='Armature', type='ARMATURE')
        modifier.object = arm_obj
        # 骨架设为模型的父级（对象本身保持无变换）
        obj.parent = arm_obj

    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj
