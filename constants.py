"""BufferIO 常量定义：语义枚举、坐标轴、目录、动态枚举辅助。"""

from pathlib import Path


# Mesh 模式的语义枚举：(标识符, 显示名, 说明)
# 标识符即导入时使用的语义关键字，与 3dmigoto/DXGI 命名一致
# INDEX 为三角形索引缓冲（支持直接解析 3dmigoto ib txt）
ATTRIBUTE_SEMANTIC_ITEMS = [
    ('INDEX', 'INDEX', '三角形索引缓冲（支持 3dmigoto ib txt 直接解析）'),
    ('POSITION', 'POSITION', '顶点位置'),
    ('TANGENT', 'TANGENT', '顶点切线'),
    ('NORMAL', 'NORMAL', '顶点法线'),
    ('COLOR', 'COLOR', '顶点色'),
    ('TEXCOORD', 'TEXCOORD', 'UV 贴图坐标'),
    ('BLENDINDICES', 'BLENDINDICES', '骨骼权重索引'),
    ('BLENDWEIGHTS', 'BLENDWEIGHTS', '骨骼权重值'),
    ('SHAPEKEY_OFFSET', 'SHAPEKEY_OFFSET', '形态键顶点偏移边界（R32_UINT，如 [0,1244,...]）'),
    ('SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXID', '形态键顶点 id 列表（R32_UINT）'),
    ('SHAPEKEY_VERTEXOFFSET', 'SHAPEKEY_VERTEXOFFSET', '形态键顶点位移向量列表（R16G16B16_FLOAT）'),
    ('SHAPEKEY', 'SHAPEKEY', '形态键逐顶点位移（R16G16B16_FLOAT，索引即 Deform 编号，如 SHAPEKEY 23 = Deform 23 的位移）'),
]

# FMT 模式的语义枚举：比 Mesh 模式多一个 SKIP（不导入该元素）
# 加载 FMT 时按 SEMANTIC_GUESS 自动猜测，用户可在列表中手动修正
ELEMENT_SEMANTIC_ITEMS = [
    ('SKIP', 'SKIP', '不导入该元素'),
    ('INDEX', 'INDEX', '三角形索引缓冲'),
    ('POSITION', 'POSITION', '顶点位置'),
    ('TANGENT', 'TANGENT', '顶点切线'),
    ('NORMAL', 'NORMAL', '顶点法线'),
    ('COLOR', 'COLOR', '顶点色'),
    ('TEXCOORD', 'TEXCOORD', 'UV 贴图坐标'),
    ('BLENDINDICES', 'BLENDINDICES', '骨骼权重索引'),
    ('BLENDWEIGHTS', 'BLENDWEIGHTS', '骨骼权重值'),
    ('SHAPEKEY_OFFSET', 'SHAPEKEY_OFFSET', '形态键顶点偏移边界（R32_UINT，如 [0,1244,...]）'),
    ('SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXID', '形态键顶点 id 列表（R32_UINT）'),
    ('SHAPEKEY_VERTEXOFFSET', 'SHAPEKEY_VERTEXOFFSET', '形态键顶点位移向量列表（R16G16B16_FLOAT）'),
    ('SHAPEKEY', 'SHAPEKEY', '形态键逐顶点位移（R16G16B16_FLOAT，索引即 Deform 编号，如 SHAPEKEY 23 = Deform 23 的位移）'),
]

# 可以有多个索引（如 TEXCOORD0-3）的语义
INDEXED_SEMANTICS = {
    'TEXCOORD', 'COLOR', 'BLENDINDICES', 'BLENDWEIGHTS',
    'SHAPEKEY_OFFSET', 'SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXOFFSET',
    'SHAPEKEY',
}

# 需要转换为浮点的语义
FLOAT_SEMANTICS = {
    'POSITION', 'NORMAL', 'TANGENT', 'TEXCOORD', 'COLOR', 'BLENDWEIGHTS',
    'SHAPEKEY_VERTEXOFFSET', 'SHAPEKEY',
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
}

# 形态键相关语义（按偏移边界组合成 Blender 形态键）
SHAPEKEY_SEMANTICS = {
    'SHAPEKEY_OFFSET', 'SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXOFFSET',
}

AXIS_ITEMS = [
    ('X', 'X', ''),
    ('Y', 'Y', ''),
    ('Z', 'Z', ''),
    ('-X', '-X', ''),
    ('-Y', '-Y', ''),
    ('-Z', '-Z', ''),
]

# 语义方案保存目录：插件安装目录下（不随 .blend 工程变化）
SEMANTICS_DIR = Path(__file__).resolve().parent / 'semantics'
# Mesh 预设保存目录
MESH_PRESETS_DIR = Path(__file__).resolve().parent / 'mesh_presets'


def _semantics_items(self, context):
    """动态枚举插件本地已保存的语义方案"""
    items = []
    if SEMANTICS_DIR.is_dir():
        for i, path in enumerate(sorted(SEMANTICS_DIR.glob('*.json'))):
            items.append((path.stem, path.stem, str(path)))
    if not items:
        items.append(('', '（无已保存方案）', ''))
    return items


def _mesh_preset_items(self, context):
    """动态枚举插件本地已保存的 Mesh 预设"""
    items = []
    if MESH_PRESETS_DIR.is_dir():
        for i, path in enumerate(sorted(MESH_PRESETS_DIR.glob('*.json'))):
            items.append((path.stem, path.stem, str(path)))
    if not items:
        items.append(('', '（无已保存预设）', ''))
    return items
