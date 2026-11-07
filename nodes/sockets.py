"""BufferIO 自定义节点 Socket：按数据类型区分颜色与形状，只表达拓扑连线。

与原生节点一致的默认值模型：值类 Socket（String/Float/Int/Bool/Format）
自带 default_value，未连接时直接在端口上编辑。
"""

import bpy

from .. import dxgi
from ..constants import INDEXED_SEMANTICS

# Socket 类型 -> 颜色（RGBA）
SOCKET_COLORS = {
    'BufferIOSocketArray': (0.30, 0.55, 1.00, 1.0),      # 数组：蓝
    'BufferIOSocketIndex': (1.00, 0.58, 0.15, 1.0),      # 索引：橙
    'BufferIOSocketBoneMatrix': (0.95, 0.30, 0.30, 1.0),  # 骨骼矩阵：红
    'BufferIOSocketShapeKey': (0.95, 0.80, 0.20, 1.0),   # 形态键：黄
    'BufferIOSocketMesh': (0.70, 0.35, 1.00, 1.0),       # 网格：紫
    'BufferIOSocketFormat': (0.22, 0.78, 0.78, 1.0),     # 格式：青
    'BufferIOSocketString': (0.82, 0.52, 0.82, 1.0),     # 字符串：粉紫
    'BufferIOSocketFloat': (0.62, 0.62, 0.62, 1.0),      # 浮点值：灰
    'BufferIOSocketInt': (0.80, 0.80, 0.80, 1.0),        # 整数值：浅灰
    'BufferIOSocketBool': (0.90, 0.45, 0.60, 1.0),       # 布尔：粉
    'BufferIOSocketFile': (0.35, 0.65, 0.85, 1.0),       # 文件路径：蓝灰
}

# Socket 类型 -> 形状（CIRCLE / SQUARE / DIAMOND / *_DOT / LINE / LIST）
SOCKET_SHAPES = {
    'BufferIOSocketArray': 'CIRCLE',
    'BufferIOSocketIndex': 'SQUARE_DOT',
    'BufferIOSocketBoneMatrix': 'DIAMOND',
    'BufferIOSocketShapeKey': 'DIAMOND_DOT',
    'BufferIOSocketMesh': 'CIRCLE_DOT',
    'BufferIOSocketFormat': 'SQUARE',
    'BufferIOSocketString': 'DIAMOND',
    'BufferIOSocketFloat': 'CIRCLE',
    'BufferIOSocketInt': 'CIRCLE_DOT',
    'BufferIOSocketBool': 'DIAMOND',
    'BufferIOSocketFile': 'SQUARE',
}


def _semantic_label(node, socket=None):
    """推导这条连线承载的语义，用于 Socket 文字提示"""
    semantic = getattr(node, 'semantic', '')
    if not semantic or semantic in {'SKIP', 'INDEX'}:
        return ''
    index = getattr(node, 'semantic_index', None)
    if index is None:
        target = getattr(node, 'target_index', -1)
        index = target if target >= 0 else getattr(node, 'source_index', 0)
    if semantic in INDEXED_SEMANTICS and index:
        return f'{semantic}{index}'
    return semantic


def _has_default_value(socket):
    return socket.bl_rna.properties.get('default_value') is not None


class _BufferIOSocketBase(bpy.types.NodeSocket):
    """按数据类型着色的 Socket 基类（子类只覆盖 COLOR）"""

    bl_label = 'Buffer Data'
    COLOR = (0.30, 0.55, 1.00, 1.0)

    def draw(self, context, layout, node, text):
        if self.is_output:
            layout.label(text=text)
            return
        if self.is_linked:
            # 多输入端口：显示已连接的数量
            if self.is_multi_input and len(self.links) > 1:
                layout.label(text=f'{text}  x{len(self.links)}')
                return
            link = self.links[0]
            semantic = _semantic_label(link.from_node, link.from_socket)
            layout.label(text=f'{text}  {semantic}' if semantic else text)
            return
        # 未连接的输入端口直接编辑 socket 自带的默认值（与原生 socket 一致）
        if _has_default_value(self):
            layout.prop(self, 'default_value', text=text)
            return
        layout.label(text=text)

    @classmethod
    def draw_color_simple(cls):
        return cls.COLOR


class BufferIOSocketArray(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketArray'
    bl_label = 'Array'
    COLOR = SOCKET_COLORS['BufferIOSocketArray']


class BufferIOSocketIndex(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketIndex'
    bl_label = 'Index'
    COLOR = SOCKET_COLORS['BufferIOSocketIndex']


class BufferIOSocketBoneMatrix(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketBoneMatrix'
    bl_label = 'Bone Matrix'
    COLOR = SOCKET_COLORS['BufferIOSocketBoneMatrix']


class BufferIOSocketShapeKey(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketShapeKey'
    bl_label = 'Shape Key'
    COLOR = SOCKET_COLORS['BufferIOSocketShapeKey']


class BufferIOSocketMesh(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketMesh'
    bl_label = 'Mesh'
    COLOR = SOCKET_COLORS['BufferIOSocketMesh']


class BufferIOSocketFormat(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketFormat'
    bl_label = 'Format'
    COLOR = SOCKET_COLORS['BufferIOSocketFormat']

    default_value: bpy.props.EnumProperty(
        name='Format', items=dxgi.FORMAT_ENUM_ITEMS,
        default='R32G32B32_FLOAT')


class BufferIOSocketString(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketString'
    bl_label = 'String'
    COLOR = SOCKET_COLORS['BufferIOSocketString']

    default_value: bpy.props.StringProperty(name='Value', default='')


class BufferIOSocketFloat(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketFloat'
    bl_label = 'Float'
    COLOR = SOCKET_COLORS['BufferIOSocketFloat']

    default_value: bpy.props.FloatProperty(name='Value', default=0.0)


class BufferIOSocketInt(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketInt'
    bl_label = 'Int'
    COLOR = SOCKET_COLORS['BufferIOSocketInt']

    default_value: bpy.props.IntProperty(name='Value', default=0)


class BufferIOSocketBool(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketBool'
    bl_label = 'Bool'
    COLOR = SOCKET_COLORS['BufferIOSocketBool']

    default_value: bpy.props.BoolProperty(name='Value', default=False)


class BufferIOSocketFile(_BufferIOSocketBase):
    """文件路径：default_value 用 FILE_PATH 子类型，端口上自带文件夹浏览按钮"""
    bl_idname = 'BufferIOSocketFile'
    bl_label = 'File'
    COLOR = SOCKET_COLORS['BufferIOSocketFile']

    default_value: bpy.props.StringProperty(
        name='Path', subtype='FILE_PATH', default='')


# ---------------------------------------------------------------------------
# 节点组接口 Socket：让 BufferIO 树可以被打包为节点组（与原生节点组一致）
# ---------------------------------------------------------------------------

class _BufferIOInterfaceSocketBase(bpy.types.NodeTreeInterfaceSocket):
    """节点组接口 Socket 基类：接口默认值与成员 socket 默认值双向同步"""

    def draw(self, context, layout):
        if _has_default_value(self):
            layout.prop(self, 'default_value')

    def init_socket(self, node, socket, data_path):
        if _has_default_value(socket):
            socket.default_value = self.default_value

    def from_socket(self, node, socket):
        if _has_default_value(socket):
            self.default_value = socket.default_value


class BufferIOInterfaceSocketArray(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketArray'
    bl_label = 'Array'
    bl_socket_idname = 'BufferIOSocketArray'


class BufferIOInterfaceSocketIndex(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketIndex'
    bl_label = 'Index'
    bl_socket_idname = 'BufferIOSocketIndex'


class BufferIOInterfaceSocketBoneMatrix(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketBoneMatrix'
    bl_label = 'Bone Matrix'
    bl_socket_idname = 'BufferIOSocketBoneMatrix'


class BufferIOInterfaceSocketShapeKey(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketShapeKey'
    bl_label = 'Shape Key'
    bl_socket_idname = 'BufferIOSocketShapeKey'


class BufferIOInterfaceSocketMesh(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketMesh'
    bl_label = 'Mesh'
    bl_socket_idname = 'BufferIOSocketMesh'


class BufferIOInterfaceSocketFormat(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketFormat'
    bl_label = 'Format'
    bl_socket_idname = 'BufferIOSocketFormat'

    default_value: bpy.props.EnumProperty(
        name='Format', items=dxgi.FORMAT_ENUM_ITEMS,
        default='R32G32B32_FLOAT')


class BufferIOInterfaceSocketString(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketString'
    bl_label = 'String'
    bl_socket_idname = 'BufferIOSocketString'

    default_value: bpy.props.StringProperty(name='Value', default='')


class BufferIOInterfaceSocketFloat(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketFloat'
    bl_label = 'Float'
    bl_socket_idname = 'BufferIOSocketFloat'

    default_value: bpy.props.FloatProperty(name='Value', default=0.0)


class BufferIOInterfaceSocketInt(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketInt'
    bl_label = 'Int'
    bl_socket_idname = 'BufferIOSocketInt'

    default_value: bpy.props.IntProperty(name='Value', default=0)


class BufferIOInterfaceSocketBool(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketBool'
    bl_label = 'Bool'
    bl_socket_idname = 'BufferIOSocketBool'

    default_value: bpy.props.BoolProperty(name='Value', default=False)


class BufferIOInterfaceSocketFile(_BufferIOInterfaceSocketBase):
    bl_idname = 'BufferIOInterfaceSocketFile'
    bl_label = 'File'
    bl_socket_idname = 'BufferIOSocketFile'

    default_value: bpy.props.StringProperty(
        name='Path', subtype='FILE_PATH', default='')


def _apply_shape(socket, idname):
    socket.display_shape = SOCKET_SHAPES.get(idname, 'CIRCLE')


def new_input(node, idname, name, multi_input=False):
    """创建输入端口；multi_input=True 时用几何节点那样的长条多输入端口"""
    if multi_input:
        socket = node.inputs.new(idname, name, use_multi_input=True)
    else:
        socket = node.inputs.new(idname, name)
    _apply_shape(socket, idname)
    return socket


def new_output(node, idname, name):
    socket = node.outputs.new(idname, name)
    _apply_shape(socket, idname)
    return socket


CLASSES = (
    BufferIOSocketArray,
    BufferIOSocketIndex,
    BufferIOSocketBoneMatrix,
    BufferIOSocketShapeKey,
    BufferIOSocketMesh,
    BufferIOSocketFormat,
    BufferIOSocketString,
    BufferIOSocketFloat,
    BufferIOSocketInt,
    BufferIOSocketBool,
    BufferIOSocketFile,
    BufferIOInterfaceSocketArray,
    BufferIOInterfaceSocketIndex,
    BufferIOInterfaceSocketBoneMatrix,
    BufferIOInterfaceSocketShapeKey,
    BufferIOInterfaceSocketMesh,
    BufferIOInterfaceSocketFormat,
    BufferIOInterfaceSocketString,
    BufferIOInterfaceSocketFloat,
    BufferIOInterfaceSocketInt,
    BufferIOInterfaceSocketBool,
    BufferIOInterfaceSocketFile,
)
