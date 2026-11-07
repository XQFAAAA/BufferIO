"""BufferIO 常量定义：语义枚举、坐标轴、算法选项。"""


# FMT 模式的语义枚举
# 标识符即导入时使用的语义关键字，与 3dmigoto/DXGI 命名一致
# INDEX 为三角形索引缓冲（支持直接解析 3dmigoto ib txt），显示名为 Index Buffer
ELEMENT_SEMANTIC_ITEMS = [
    ('SKIP', 'SKIP', 'Do not import this element'),
    ('INDEX', 'Index Buffer', 'Triangle index buffer'),
    ('POSITION', 'POSITION', 'Vertex position'),
    ('TANGENT', 'TANGENT', 'Vertex tangent'),
    ('NORMAL', 'NORMAL', 'Vertex normal'),
    ('COLOR', 'COLOR', 'Vertex color'),
    ('TEXCOORD', 'TEXCOORD', 'UV coordinates'),
    ('BLENDINDICES', 'BLENDINDICES', 'Blend indices'),
    ('BLENDWEIGHTS', 'BLENDWEIGHTS', 'Blend weights'),
    ('SHAPEKEY_OFFSET', 'SHAPEKEY_OFFSET', 'Shape key vertex offset bounds (R32_UINT, e.g. [0,1244,...])'),
    ('SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXID', 'Shape key vertex id list (R32_UINT)'),
    ('SHAPEKEY_VERTEXOFFSET', 'SHAPEKEY_VERTEXOFFSET', 'Shape key vertex offset vector list (R16G16B16_FLOAT)'),
    ('SHAPEKEY', 'SHAPEKEY', 'Per-vertex shape key offset (R16G16B16_FLOAT; the index is the Deform index, e.g. SHAPEKEY 23 = offset of Deform 23)'),
    ('BONEMATRIX', 'BONEMATRIX', 'Bone 3x4 matrix (MATRIX3X4_FLOAT; the index is the bone index, matching BLENDINDICES)'),
]

# 可以有多个索引（如 TEXCOORD0-3）的语义
INDEXED_SEMANTICS = {
    'TEXCOORD', 'COLOR', 'BLENDINDICES', 'BLENDWEIGHTS',
    'SHAPEKEY_OFFSET', 'SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXOFFSET',
    'SHAPEKEY', 'BONEMATRIX',
}

# 需要转换为浮点的语义
FLOAT_SEMANTICS = {
    'POSITION', 'NORMAL', 'TANGENT', 'TEXCOORD', 'COLOR', 'BLENDWEIGHTS',
    'SHAPEKEY_VERTEXOFFSET', 'SHAPEKEY', 'BONEMATRIX',
}

SEMANTIC_GUESS = {
    'POSITION': 'POSITION',
    'NORMAL': 'NORMAL',
    'TANGENT': 'TANGENT',
    'BLENDINDICES': 'BLENDINDICES',
    'BLENDWEIGHT': 'BLENDWEIGHTS',
    'BLENDWEIGHTS': 'BLENDWEIGHTS',
    'TEXCOORD': 'TEXCOORD',
    'COLOR': 'COLOR',
    'SHAPEKEY_OFFSET': 'SHAPEKEY_OFFSET',
    'SHAPEKEY_VERTEXID': 'SHAPEKEY_VERTEXID',
    'SHAPEKEY_VERTEXOFFSET': 'SHAPEKEY_VERTEXOFFSET',
    'SHAPEKEY': 'SHAPEKEY',
    'BONEMATRIX': 'BONEMATRIX',
}

# 形态键相关语义（按偏移边界组合成 Blender 形态键）
SHAPEKEY_SEMANTICS = {
    'SHAPEKEY_OFFSET', 'SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXOFFSET',
}

# 资源节点（Vertex Buffer / Index Buffer / Shape Key / Bone Matrix）的解码算法
# 目前只有「保持」，后续算法在此追加（追加不会影响已保存文件，静态枚举按标识符存储）
ALGORITHM_ITEMS = [
    ('KEEP', 'Default', 'Decode per the format spec'),
]

# 骨骼矩阵算法：正交矩阵模式跳过旋转非正交的骨骼，但保留原编号
BONE_MATRIX_ALGORITHM_ITEMS = [
    ('KEEP', 'Default', 'Decode per the format spec'),
    ('ORTHOGONAL', 'Orthogonal',
     'Skip bones whose rotation matrix is not orthogonal (indices unchanged)'),
]

AXIS_ITEMS = [
    ('X', 'X', ''),
    ('Y', 'Y', ''),
    ('Z', 'Z', ''),
    ('-X', '-X', ''),
    ('-Y', '-Y', ''),
    ('-Z', '-Z', ''),
]

# 语义映射预设以 Blender 原生操作项预设形式分发：
# presets/operator/bufferio_import_fmt/*.py（WuWa 预设由 __init__.py 注册路径后出现在
# 「Import from FMT」右侧的下拉菜单中）。映射条目为 (SemanticName, SemanticIndex)
# -> (semantic, target_index)，target_index 写入节点的 Semantic Index，
# 并决定 BLENDINDICES/WEIGHTS 的拼接顺序。
