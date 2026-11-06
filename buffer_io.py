"""网格 / 骨架对象的构建。

二进制读取与顶点压缩在 storage.py，这里只负责把数据写成 Blender 对象；
本模块继续重导出读取接口，旧的 ``from .buffer_io import read_buffer`` 仍然可用。
"""

import bmesh
import numpy
import bpy

from .storage import (
    BufferIOError,
    compact_vertices,
    read_buffer,
    read_indices,
    read_indices_from_ib_txt,
)


def _transformed(array, scale=1.0, mirror_x=False, rot=None, apply_scale=False):
    """复制一份并依次应用缩放 / 镜像 / 轴转换，不改动调用方的数组"""
    out = numpy.array(numpy.asarray(array, dtype=numpy.float32), copy=True)
    if out.ndim == 1:
        out = out.reshape(-1, 1)
    if apply_scale and scale != 1.0:
        out *= scale
    if mirror_x:
        out[:, 0] *= -1
    if rot is not None and out.shape[1] >= 3:
        out[:, :3] = out[:, :3] @ rot.T
    return out


def build_object(name, faces, positions, normals=None, tangents=None, uvs=None,
                 colors=None, blend_indices=None, blend_weights=None,
                 shape_keys=None, shape_key_arrays=None, vertex_map=None,
                 flip_winding=True, flip_texcoord_v=True,
                 scale=1.0, mirror_x=False, conversion=None):
    """根据缓冲数据构建 Blender 网格对象

    faces:         (n, 3) 索引数组
    positions:     (n, 3+) 顶点位置
    normals:       (n, 3+) 顶点法线
    tangents:      (n, 4) 顶点切线
    uvs:           {semantic_index: (n, 2+) uv 数组}
    colors:        {semantic_index: (n, 3+) 顶点色数组}
    blend_indices: {semantic_index: (n, k) 权重索引数组}
    blend_weights: {semantic_index: (n, k) 权重值数组}
    shape_keys:    (offsets, vertex_ids, vertex_offsets) 三元组，
                   offsets[i]/offsets[i+1] 界定第 i 个形态键在 vertex_ids/vertex_offsets
                   中的范围，vertex_offsets 为该顶点 id 对应的位移向量。
    shape_key_arrays: {semantic_index: (n, 3) 位移数组}，逐顶点形态键，
                   键即 Deform 编号（如 SHAPEKEY 23 -> Deform 23）。
    vertex_map:    顶点压缩映射（vertex_map[旧编号] = 新编号，未引用为 -1），
                   用于把形态键的原始顶点 id 重定向到压缩后的网格；None = 未压缩
    scale:         全局缩放系数（作用于顶点位置）
    mirror_x:      沿 X 轴镜像（同时翻转法线/切线 X 分量，并反转环绕方向）
    conversion:    坐标轴转换矩阵（mathutils 4×4），作用于顶点/法线/切线/形态键位移，
                   对象本身保持无变换
    """
    uvs = uvs or {}
    colors = colors or {}
    blend_indices = blend_indices or {}
    blend_weights = blend_weights or {}

    # 镜像会使三角形环绕方向反转，等价于对 flip_winding 取异或
    if flip_winding != mirror_x:
        faces = numpy.ascontiguousarray(faces[:, ::-1])

    vertex_ids = numpy.ascontiguousarray(faces, dtype=numpy.int32).reshape(-1)
    num_faces = len(faces)

    rot = numpy.array(conversion.to_3x3()) if conversion is not None else None

    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)

    positions = _transformed(positions[:, :3], scale, mirror_x, rot, apply_scale=True)
    mesh.vertices.add(len(positions))
    mesh.vertices.foreach_set('co', positions.reshape(-1))

    # 面
    mesh.loops.add(num_faces * 3)
    mesh.polygons.add(num_faces)
    mesh.loops.foreach_set('vertex_index', vertex_ids)
    mesh.polygons.foreach_set(
        'loop_start', (numpy.arange(num_faces, dtype=numpy.int32) * 3))
    mesh.polygons.foreach_set('loop_total', numpy.full(num_faces, 3, dtype=numpy.int32))
    mesh.polygons.foreach_set('use_smooth', numpy.ones(num_faces, dtype=bool))

    # 顶点权重（bmesh 写入，放在 UV / 顶点色之前，避免来回转换自定义数据层）
    mesh.update()
    _import_vertex_groups(obj, blend_indices, blend_weights)

    # UV（逐 loop，需要按顶点索引展开）
    for uv_index in sorted(uvs.keys()):
        # 复制后再翻转，避免改动调用方传入的 UV 数组
        data = numpy.array(uvs[uv_index][:, :2], dtype=numpy.float32, copy=True)
        if flip_texcoord_v:
            data[:, 1] = 1.0 - data[:, 1]
        uv_name = f'TEXCOORD{uv_index or ""}.xy'
        mesh.uv_layers.new(name=uv_name)
        mesh.uv_layers[uv_name].data.foreach_set(
            'uv', data[vertex_ids].reshape(-1))

    # 顶点色：数据本身按顶点存储，使用 POINT 域（不复制成 CORNER）
    for color_index in sorted(colors.keys()):
        data = colors[color_index]
        if data.shape[1] == 3:
            data = numpy.concatenate(
                [data, numpy.ones((len(data), 1), dtype=data.dtype)], axis=1)
        data = numpy.ascontiguousarray(data[:, :4], dtype=numpy.float32)
        color_name = f'COLOR{color_index or ""}'
        attribute = mesh.color_attributes.new(
            name=color_name, type='FLOAT_COLOR', domain='POINT')
        attribute.data.foreach_set('color', data.reshape(-1))

    # 形态键：按 ShapeKeyOffset 边界切分 VertexId/VertexOffset，
    # 或按 SHAPEKEY 逐顶点位移数组直接生成
    if shape_keys is not None or shape_key_arrays:
        _import_shape_keys(obj, shape_keys, shape_key_arrays=shape_key_arrays,
                           vertex_map=vertex_map, scale=scale, mirror_x=mirror_x,
                           rot=rot)

    # 切线存入自定义属性（Blender 无原生切线存储）
    if tangents is not None:
        data = _transformed(tangents[:, :3], mirror_x=mirror_x, rot=rot)
        attribute = mesh.attributes.new(name='TANGENT', type='FLOAT_VECTOR', domain='POINT')
        attribute.data.foreach_set('vector', data.reshape(-1))

    # 生成缺失的网格元数据
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update()

    # 自定义法线（需在网格构建完成后写入）
    # 该参数是「每顶点一个三元向量」的序列，必须传 list[list[float]]；
    # 扁平数组或 numpy 标量都会被拒绝
    if normals is not None:
        data = _transformed(normals[:, :3], mirror_x=mirror_x, rot=rot)
        if len(data) == len(positions):
            mesh.normals_split_custom_set_from_vertices(data.tolist())

    return obj


def _collect_used_bone_indices(indices):
    """从骨骼索引数组收集实际使用到的骨骼索引集合（未引用即无效/未使用槽位）"""
    arr = numpy.asarray(indices)
    if arr.size == 0:
        return set()
    return set(int(i) for i in numpy.unique(arr))


def _import_vertex_groups(obj, blend_indices, blend_weights):
    """写入顶点组权重

    用 bmesh 的 deform 层一次性写回：比逐次调用 vertex_group.add 的 RNA 开销低得多。
    """
    if not blend_indices or not blend_weights:
        return

    # 多对 BLENDINDICES / BLENDWEIGHTS 按顺序拼接成完整数组后统一对应
    # （如两对 ATTRIBUTE 3/14 索引 + 4/15 权重 -> 每顶点 8 索引 + 8 权重顺序对应）
    idx_keys = sorted(blend_indices.keys())
    wt_keys = sorted(blend_weights.keys())
    pairs = min(len(idx_keys), len(wt_keys))
    if pairs == 0:
        return

    def to_2d(array):
        array = numpy.asarray(array)
        return array.reshape(-1, 1) if array.ndim == 1 else array

    indices = numpy.concatenate(
        [to_2d(blend_indices[k]) for k in idx_keys[:pairs]], axis=1).astype(numpy.int64)
    weights = numpy.concatenate(
        [to_2d(blend_weights[k]) for k in wt_keys[:pairs]], axis=1).astype(numpy.float32)

    # 只创建实际被引用到的骨骼组（跳过缓冲中的无效索引）
    used = _collect_used_bone_indices(indices)
    if not used:
        return

    bone_ids = sorted(used)
    for bone in bone_ids:
        obj.vertex_groups.new(name=str(bone))
    bone_to_group = {bone: position for position, bone in enumerate(bone_ids)}

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        deform = bm.verts.layers.deform.verify()
        verts = bm.verts
        verts.ensure_lookup_table()
        limit = min(len(indices), len(verts))
        active = numpy.nonzero((weights > 0.0).any(axis=1))[0]
        for vertex_id in active:
            if vertex_id >= limit:
                continue
            dvert = verts[int(vertex_id)][deform]
            for bone, weight in zip(indices[vertex_id], weights[vertex_id]):
                if weight <= 0.0:
                    continue
                group = bone_to_group.get(int(bone))
                if group is not None:
                    dvert[group] = float(weight)
        bm.to_mesh(obj.data)
    finally:
        bm.free()


def _import_shape_keys(obj, shape_keys, shape_key_arrays=None,
                       vertex_map=None, scale=1.0, mirror_x=False, rot=None):
    """构建 Blender 形态键

    shape_keys:  [(offsets, vertex_ids, vertex_offsets), ...] 列表，
                 每个元素是一组（按索引分组，如索引 0 一组、索引 1 一组...）。
                 offsets 为 (k+1,) 每个形态键在 vertex_ids 中的起始边界，如 [0,1244,2480,...]；
                 vertex_ids 为该形态键包含的顶点 id；vertex_offsets 为对应位移向量。
    shape_key_arrays: {semantic_index: (n, 3) 位移数组}，逐顶点形态键，
                索引即 Deform 编号（如 SHAPEKEY 23 -> Deform 23）。
    vertex_map:  顶点压缩映射，把原始顶点 id 重定向到压缩后的网格
    """
    if not shape_keys and not shape_key_arrays:
        return

    obj.shape_key_add(name='Basis', from_mix=False)
    basis_data = numpy.empty(len(obj.data.vertices) * 3, dtype=numpy.float32)
    obj.data.vertices.foreach_get('co', basis_data)
    basis_data = basis_data.reshape(-1, 3)
    vertex_count = len(basis_data)

    def make_key(name, vecs):
        """以基础坐标 + 位移生成形态键，位移作用于全部顶点（vecs 为 (n,3)）"""
        key = obj.shape_key_add(name=name, from_mix=False)
        key.value = 0.0  # 导入后形态键数值归零，显示基础网格
        key.data.foreach_set('co', (basis_data + vecs).reshape(-1))
        return key

    def map_ids(ids):
        """原始顶点 id -> 压缩后网格顶点 id（无效的置 -1）"""
        ids = numpy.asarray(ids, dtype=numpy.int64)
        if vertex_map is None:
            return ids.copy()
        mapped = numpy.full(len(ids), -1, dtype=numpy.int64)
        valid = (ids >= 0) & (ids < len(vertex_map))
        mapped[valid] = vertex_map[ids[valid]]
        return mapped

    # 形态键名称编号跨组全局累加（如索引 0 生成 Deform 0..126，索引 1 从 Deform 127 开始）
    deform_index = 0
    for offsets, vertex_ids, vertex_offsets in shape_keys or []:
        offsets = numpy.asarray(offsets, dtype=numpy.int64)
        ids_all = map_ids(vertex_ids)
        vecs_all = _transformed(vertex_offsets, scale, mirror_x, rot, apply_scale=True)

        count = len(offsets) - 1
        for i in range(count):
            start = int(offsets[i])
            end = int(offsets[i + 1]) if i + 1 < len(offsets) else len(ids_all)
            if start >= end or start >= len(ids_all):
                continue
            ids = ids_all[start:end]
            vecs = vecs_all[start:end]

            key = obj.shape_key_add(name=f'Deform {deform_index}', from_mix=False)
            deform_index += 1
            key.value = 0.0
            # 形态键坐标为绝对坐标 = 基础坐标 + 位移
            data = basis_data.copy()
            valid = (ids >= 0) & (ids < vertex_count)
            data[ids[valid]] += vecs[valid]
            key.data.foreach_set('co', data.reshape(-1))

    # 逐顶点形态键：SHAPEKEY 索引即 Deform 编号
    if shape_key_arrays:
        for index in sorted(shape_key_arrays.keys()):
            vecs = _transformed(shape_key_arrays[index][:, :3], scale, mirror_x, rot,
                                apply_scale=True)
            if len(vecs) == vertex_count:
                make_key(f'Deform {index}', vecs)


def build_armature(name, matrices, scale=1.0, mirror_x=False, conversion=None,
                   collection=None, indices=None):
    """创建骨架对象：骨骼 rest 全部位于原点（无父子），姿态应用骨骼矩阵

    matrices: (n, 3, 4) 行主序 3×4 蒙皮矩阵（索引即骨骼号）
    indices:  可选，实际使用到的骨骼索引集合；仅创建这些骨骼（按原索引命名），
              跳过缓冲中未被顶点组引用（无效/未使用）的槽位；None = 创建全部骨骼。
    scale:    全局缩放，与网格顶点缩放一致（先作用于骨骼平移，再做轴相似变换）
    mirror_x: 沿 X 轴镜像（与网格顶点镜像一致，骨骼矩阵做 X·M·X 相似变换）
    conversion: 坐标轴转换矩阵（mathutils 4×4），骨骼矩阵做相似变换 C·M·C⁻¹，
                与顶点/法线的轴转换保持一致，对象本身保持无变换
    collection: 骨架对象链接到的集合（None = 当前场景集合）

    原理（参考 3dmigoto 官方插件）：
    骨骼沿 +Y（Blender 骨骼局部 Y 轴即 head→tail 方向）使 rest 矩阵_local = I，
    无父级时蒙皮矩阵 = pose.matrix × rest_inv = matrix_basis，
    因此把 matrix_basis 直接设为目标蒙皮矩阵即可与游戏蒙皮一致。
    骨骼名称即矩阵下标，与顶点组名称对应。
    """
    import mathutils

    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)

    if collection is None:
        collection = bpy.context.scene.collection
    collection.objects.link(arm_obj)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj

    # 仅创建被引用的骨骼（按原索引命名，跳过越界的无效索引）；bone_indices 为原索引列表
    if indices is not None:
        bone_indices = [i for i in sorted(indices) if 0 <= i < len(matrices)]
    else:
        bone_indices = list(range(len(matrices)))

    # 编辑模式创建骨骼：全部位于原点、无父级、沿 +Y 单位长度
    # （Blender 骨骼局部 Y 轴沿骨骼方向，tail 沿 +Y 时 matrix_local = I）
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        for i in bone_indices:
            bone = arm_data.edit_bones.new(str(i))
            bone.head = (0.0, 0.0, 0.0)
            bone.tail = (0.0, 0.1, 0.0)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    # 镜像矩阵（X 轴翻转，其逆等于自身）
    mirror4 = None
    if mirror_x:
        mirror4 = mathutils.Matrix((
            (-1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))

    # 姿态：零矩阵（未使用的骨骼池槽位）旋转退化，保持原点姿态即可
    for i in bone_indices:
        M = matrices[i]
        R = M[:3, :3]
        if numpy.linalg.norm(R) < 1e-4:
            continue
        T = M[:3, 3]
        target = mathutils.Matrix((
            (R[0, 0], R[0, 1], R[0, 2], T[0] * scale),
            (R[1, 0], R[1, 1], R[1, 2], T[1] * scale),
            (R[2, 0], R[2, 1], R[2, 2], T[2] * scale),
            (0.0, 0.0, 0.0, 1.0),
        ))
        # 镜像相似变换（与顶点镜像顺序一致：缩放 -> 镜像 -> 轴转换）
        if mirror4 is not None:
            target = mirror4 @ target @ mirror4
        if conversion is not None:
            target = conversion @ target @ conversion.inverted()
        arm_obj.pose.bones[str(i)].matrix_basis = target

    return arm_obj
