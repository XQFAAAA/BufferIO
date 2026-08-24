import numpy
import bpy

from pathlib import Path

from .dxgi import DXGIFormat


class BufferIOError(ValueError):
    pass


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
            f'格式 {format_name}（{fmt.byte_width} 字节）在偏移 {elem_offset} 处超出步长 {stride}')

    filepath = Path(filepath)
    data = filepath.read_bytes()
    count = (len(data) - offset) // stride
    if count <= 0:
        raise BufferIOError(f'文件 {filepath.name} 中没有可读取的数据')
    if limit > 0:
        count = min(count, limit)

    if fmt.num_values > 1 and not fmt.packed:
        field_type = (fmt.numpy_type, fmt.num_values)
    else:
        field_type = fmt.numpy_type
    dtype = numpy.dtype({
        'names': ['field'],
        'formats': [field_type],
        'offsets': [elem_offset],
        'itemsize': stride,
    })

    # numpy.frombuffer 返回只读数组，后续可能做原地变换（缩放/镜像），需复制为可写
    array = numpy.array(numpy.frombuffer(data, dtype=dtype, count=count, offset=offset)['field'], copy=True)
    if fmt.packed:
        array = fmt.unpack_packed(array)
    return array, fmt


def read_indices(filepath, format_name, stride=0, offset=0, first=0, count=0, limit=0):
    """读取索引缓冲并重组为三角形面

    first:  起始索引偏移；count: 索引数量（0 = 不限制）
    limit:  读取元素数量上限，0 = 不限制（在切片前生效）
    """
    array, fmt = read_buffer(filepath, format_name, stride=stride, offset=offset, limit=limit)
    indices = numpy.ascontiguousarray(array.reshape(-1))

    if count > 0 and first + count <= len(indices):
        indices = indices[first:first + count]
    elif first > 0:
        indices = indices[first:]

    if len(indices) % 3 != 0:
        raise BufferIOError(f'索引数量 {len(indices)} 不是 3 的倍数')

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
    numbers = []
    for raw in lines[data_start:]:
        numbers.extend(raw.split())
    if not numbers:
        raise BufferIOError(f'ib txt 中没有索引数据: {filepath.name}')

    indices = numpy.array(numbers, dtype=numpy.int64)
    if len(indices) % 3 != 0:
        raise BufferIOError(f'索引数量 {len(indices)} 不是 3 的倍数')
    return indices.reshape(-1, 3)


def compact_vertices(faces, arrays):
    """根据索引范围裁剪顶点数组并重定向索引，去除未引用的顶点

    返回 (faces, arrays, v_min)；v_min 为原始索引偏移，用于调整
    依赖原始顶点索引的数据（如形态键 vertex id）。
    """
    if faces is None or len(faces) == 0:
        return faces, arrays, 0
    v_min = int(faces.min())
    v_max = int(faces.max())
    if v_min == 0 and all(len(a) == v_max + 1 for a in arrays.values() if a is not None):
        return faces, arrays, 0
    sliced = {}
    for key, array in arrays.items():
        if array is None:
            sliced[key] = None
            continue
        if len(array) <= v_max:
            raise BufferIOError(
                f'顶点数据不足：索引最大为 {v_max}，但 {key} 只有 {len(array)} 个顶点')
        sliced[key] = numpy.ascontiguousarray(array[v_min:v_max + 1])
    return faces - v_min, sliced, v_min


def build_object(name, faces, positions, normals=None, tangents=None, uvs=None,
                 colors=None, blend_indices=None, blend_weights=None,
                 shape_keys=None, shape_key_arrays=None, shape_key_offset=0,
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
    shape_key_offset: 顶点压缩时移除的 v_min，用于把形态键顶点 id 映射到压缩后网格
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
        faces = faces[:, ::-1]

    vertex_ids = faces.reshape(-1)
    num_faces = len(faces)

    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)

    # 顶点位置（应用全局缩放与镜像）
    positions = numpy.ascontiguousarray(positions[:, :3], dtype=numpy.float32)
    if scale != 1.0:
        positions *= scale
    if mirror_x:
        positions[:, 0] *= -1
        if normals is not None:
            normals = numpy.ascontiguousarray(normals[:, :3], dtype=numpy.float32)
            normals[:, 0] *= -1
        if tangents is not None:
            tangents = numpy.ascontiguousarray(tangents[:, :3], dtype=numpy.float32)
            tangents[:, 0] *= -1
    # 坐标轴转换（作用于数据本身，对象保持无变换）
    if conversion is not None:
        rot = numpy.array(conversion.to_3x3())
        positions = positions @ rot.T
        if normals is not None:
            n = numpy.ascontiguousarray(normals, dtype=numpy.float32)
            normals = numpy.concatenate(
                [n[:, :3] @ rot.T, n[:, 3:]], axis=1) if n.shape[1] > 3 else n[:, :3] @ rot.T
        if tangents is not None:
            t = numpy.ascontiguousarray(tangents, dtype=numpy.float32)
            tangents = numpy.concatenate(
                [t[:, :3] @ rot.T, t[:, 3:]], axis=1) if t.shape[1] > 3 else t[:, :3] @ rot.T
    mesh.vertices.add(len(positions))
    mesh.vertices.foreach_set('co', positions.reshape(-1))

    # 面
    mesh.loops.add(num_faces * 3)
    mesh.polygons.add(num_faces)
    mesh.loops.foreach_set('vertex_index', vertex_ids)
    mesh.polygons.foreach_set('loop_start', numpy.arange(num_faces) * 3)
    mesh.polygons.foreach_set('loop_total', numpy.full(num_faces, 3))
    mesh.polygons.foreach_set('use_smooth', numpy.ones(num_faces, dtype=numpy.int8))

    # UV
    for uv_index in sorted(uvs.keys()):
        data = numpy.ascontiguousarray(uvs[uv_index][:, :2], dtype=numpy.float32)
        if flip_texcoord_v:
            data = data.copy()
            data[:, 1] = 1.0 - data[:, 1]
        uv_name = f'TEXCOORD{uv_index or ""}.xy'
        mesh.uv_layers.new(name=uv_name)
        mesh.uv_layers[uv_name].data.foreach_set('uv', data[vertex_ids].reshape(-1))

    # 顶点色
    for color_index in sorted(colors.keys()):
        data = colors[color_index]
        if data.shape[1] == 3:
            data = numpy.concatenate(
                [data, numpy.ones((len(data), 1), dtype=data.dtype)], axis=1)
        data = numpy.ascontiguousarray(data[:, :4], dtype=numpy.float32)
        color_name = f'COLOR{color_index or ""}'
        attribute = mesh.color_attributes.new(
            name=color_name, type='FLOAT_COLOR', domain='CORNER')
        attribute.data.foreach_set('color', data[vertex_ids].reshape(-1))

    # 顶点权重
    _import_vertex_groups(obj, blend_indices, blend_weights)

    # 形态键：按 ShapeKeyOffset 边界切分 VertexId/VertexOffset，
    # 或按 SHAPEKEY 逐顶点位移数组直接生成
    if shape_keys is not None or shape_key_arrays:
        _import_shape_keys(obj, positions, shape_keys,
                           shape_key_arrays=shape_key_arrays,
                           offset=shape_key_offset, scale=scale, mirror_x=mirror_x,
                           conversion=conversion)

    # 切线存入自定义属性（Blender 无原生切线存储）
    if tangents is not None:
        data = numpy.ascontiguousarray(tangents[:, :3], dtype=numpy.float32)
        attribute = mesh.attributes.new(name='TANGENT', type='FLOAT_VECTOR', domain='POINT')
        attribute.data.foreach_set('vector', data.reshape(-1))

    # 生成缺失的网格元数据
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update()

    # 法线（需在网格构建完成后写入）
    if normals is not None and bpy.app.version >= (4, 1):
        data = numpy.ascontiguousarray(normals[:, :3], dtype=numpy.float32)
        mesh.normals_split_custom_set_from_vertices(data)

    return obj


def _import_vertex_groups(obj, blend_indices, blend_weights):
    if not blend_indices or not blend_weights:
        return

    # 多对 BLENDINDICES / BLENDWEIGHTS 按顺序拼接成完整数组后统一对应
    # （如两对 ATTRIBUTE 3/14 索引 + 4/15 权重 -> 每顶点 8 索引 + 8 权重顺序对应）
    idx_keys = sorted(blend_indices.keys())
    wt_keys = sorted(blend_weights.keys())

    idx_parts, wt_parts = [], []
    for pos, idx_key in enumerate(idx_keys):
        if pos >= len(wt_keys):
            break
        idx_parts.append(blend_indices[idx_key])
        wt_parts.append(blend_weights[wt_keys[pos]])

    def to_2d(array):
        array = numpy.asarray(array)
        return array.reshape(-1, 1) if array.ndim == 1 else array

    indices = numpy.concatenate([to_2d(a) for a in idx_parts], axis=1).astype(numpy.int64)
    weights = numpy.concatenate([to_2d(a) for a in wt_parts], axis=1).astype(numpy.float32)

    max_index = int(indices.max()) if indices.size else -1
    if max_index < 0:
        return

    groups = [obj.vertex_groups.new(name=str(i)) for i in range(max_index + 1)]

    for vertex_id, (v_indices, v_weights) in enumerate(zip(indices, weights)):
        for index, weight in zip(v_indices, v_weights):
            if weight > 0.0:
                groups[int(index)].add((vertex_id,), float(weight), 'REPLACE')


def _import_shape_keys(obj, positions, shape_keys, shape_key_arrays=None,
                       offset=0, scale=1.0, mirror_x=False, conversion=None):
    """构建 Blender 形态键

    shape_keys:  [(offsets, vertex_ids, vertex_offsets), ...] 列表，
                 每个元素是一组（按索引分组，如索引 0 一组、索引 1 一组...）。
                 offsets 为 (k+1,) 每个形态键在 vertex_ids 中的起始边界，如 [0,1244,2480,...]；
                 vertex_ids 为该形态键包含的顶点 id；vertex_offsets 为对应位移向量。
    shape_key_arrays: {semantic_index: (n, 3) 位移数组}，逐顶点形态键，
                索引即 Deform 编号（如 SHAPEKEY 23 -> Deform 23）。
    offset:      顶点压缩时移除的 v_min，映射到压缩后网格的索引 = id - offset
    """
    if not shape_keys and not shape_key_arrays:
        return

    rot = numpy.array(conversion.to_3x3()) if conversion is not None else None

    basis = obj.shape_key_add(name='Basis', from_mix=False)
    basis_data = numpy.empty(len(positions) * 3, dtype=numpy.float32)
    obj.data.vertices.foreach_get('co', basis_data)

    def make_key(name, vecs):
        """以基础坐标 + 位移生成形态键，位移作用于全部顶点（vecs 为 (n,3)）"""
        key = obj.shape_key_add(name=name, from_mix=False)
        key.value = 0.0  # 导入后形态键数值归零，显示基础网格
        data = numpy.array(basis_data, dtype=numpy.float32).reshape(-1, 3)
        data += vecs
        key.data.foreach_set('co', data.reshape(-1))
        return key

    def transform_vecs(vecs):
        """位移向量应用与顶点相同的缩放/镜像/轴转换"""
        vecs = numpy.ascontiguousarray(vecs, dtype=numpy.float32)
        if scale != 1.0:
            vecs = vecs * scale
        if mirror_x:
            vecs = vecs.copy()
            vecs[:, 0] *= -1
        if rot is not None:
            vecs = vecs @ rot.T
        return vecs

    # 形态键名称编号跨组全局累加（如索引 0 生成 Deform 0..126，索引 1 从 Deform 127 开始）
    deform_index = 0
    for offsets, vertex_ids, vertex_offsets in shape_keys or []:
        offsets = numpy.asarray(offsets, dtype=numpy.int64)
        vertex_ids = numpy.asarray(vertex_ids, dtype=numpy.int64) - offset
        vertex_offsets = transform_vecs(vertex_offsets)

        count = len(offsets) - 1
        for i in range(count):
            start = int(offsets[i])
            end = int(offsets[i + 1]) if i + 1 < len(offsets) else len(vertex_ids)
            if start >= end or start >= len(vertex_ids):
                continue
            ids = vertex_ids[start:end]
            vecs = vertex_offsets[start:end]

            key = obj.shape_key_add(name=f'Deform {deform_index}', from_mix=False)
            deform_index += 1
            key.value = 0.0  # 导入后形态键数值归零，显示基础网格
            # 形态键坐标为绝对坐标 = 基础坐标 + 位移
            data = numpy.array(basis_data, dtype=numpy.float32).reshape(-1, 3)
            valid = (ids >= 0) & (ids < len(data))
            data[ids[valid]] += vecs[valid]
            key.data.foreach_set('co', data.reshape(-1))

    # 逐顶点形态键：SHAPEKEY 索引即 Deform 编号
    if shape_key_arrays:
        for index in sorted(shape_key_arrays.keys()):
            vecs = transform_vecs(shape_key_arrays[index][:, :3])
            make_key(f'Deform {index}', vecs)


def build_armature(name, matrices, scale=1.0, mirror_x=False, conversion=None,
                   collection=None):
    """创建骨架对象：骨骼 rest 全部位于原点（无父子），姿态应用骨骼矩阵

    matrices: (n, 3, 4) 行主序 3×4 蒙皮矩阵（索引即骨骼号）
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

    # 编辑模式创建骨骼：全部位于原点、无父级、沿 +Y 单位长度
    # （Blender 骨骼局部 Y 轴沿骨骼方向，tail 沿 +Y 时 matrix_local = I）
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        for i in range(len(matrices)):
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
    for i, M in enumerate(matrices):
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
