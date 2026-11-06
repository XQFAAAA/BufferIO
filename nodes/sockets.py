"""BufferIO 自定义节点 Socket：按数据类型区分颜色与形状，只表达拓扑连线。"""

import bpy

from ..constants import INDEXED_SEMANTICS

# Socket 类型 -> 颜色（RGBA）
SOCKET_COLORS = {
    'BufferIOSocket': (0.30, 0.55, 1.00, 1.0),           # 旧版通用（按数组处理）
    'BufferIOSocketLayout': (0.22, 0.72, 0.36, 1.0),     # 布局：绿
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
}

# Socket 类型 -> 形状（CIRCLE / SQUARE / DIAMOND / *_DOT / LINE / LIST）
SOCKET_SHAPES = {
    'BufferIOSocket': 'CIRCLE',
    'BufferIOSocketLayout': 'SQUARE',
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
}


def _semantic_label(node, socket=None):
    """推导这条连线承载的语义，用于 Socket 文字提示"""
    if getattr(node, 'bl_idname', '') == 'BufferIOSourceFile':
        # VB ELEMENT DESC 的输出端口名本身就是目标语义（POSITION / TEXCOORD1 …）
        return socket.name if socket is not None else ''
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
        # 节点可自定义未连接端口的控件（节点组用它绘制输入默认值）
        hook = getattr(node, 'draw_socket_default', None)
        if hook is not None and hook(layout, self, text):
            return
        # 未连接的输入端口直接编辑节点属性，避免节点上再重复一套控件
        prop = getattr(node, 'SOCKET_PROPERTIES', {}).get(self.name)
        if prop and node.bl_rna.properties.get(prop) is not None:
            layout.prop(node, prop, text=text)
            return
        layout.label(text=text)

    def draw_color(self, context, node):
        return self.COLOR


class BufferIOSocket(_BufferIOSocketBase):
    """旧版通用 Socket（已保存的节点树继续可用）"""
    bl_idname = 'BufferIOSocket'


class BufferIOSocketLayout(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketLayout'
    bl_label = 'Layout'
    COLOR = SOCKET_COLORS['BufferIOSocketLayout']


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


class BufferIOSocketString(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketString'
    bl_label = 'String'
    COLOR = SOCKET_COLORS['BufferIOSocketString']


class BufferIOSocketFloat(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketFloat'
    bl_label = 'Float'
    COLOR = SOCKET_COLORS['BufferIOSocketFloat']


class BufferIOSocketInt(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketInt'
    bl_label = 'Int'
    COLOR = SOCKET_COLORS['BufferIOSocketInt']


class BufferIOSocketBool(_BufferIOSocketBase):
    bl_idname = 'BufferIOSocketBool'
    bl_label = 'Bool'
    COLOR = SOCKET_COLORS['BufferIOSocketBool']


def _apply_shape(socket, idname):
    try:
        socket.display_shape = SOCKET_SHAPES.get(idname, 'CIRCLE')
    except Exception:
        pass


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
    BufferIOSocket,
    BufferIOSocketLayout,
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
)
