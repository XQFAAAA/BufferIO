"""值节点：格式 / 字符串 / 浮点 / 整数 / 布尔，向其它节点输出常量。

与 Blender 原生值节点一致：节点上可编辑，求值结果就是该值本身，
供 IndexBuffer / Vertex Buffer / 骨骼矩阵 / 形态键 / 网格装配 / Import
等节点的输入端口使用（端口已连接时优先于节点属性）。
"""

from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from .. import dxgi
from .base import BufferIONode


class BUFFERIO_NODE_value_format(BufferIONode):
    bl_idname = 'BufferIOValueFormat'
    bl_label = 'Format'
    bl_description = 'Output a DXGI buffer format (can be wired into the Format input of other nodes)'
    bl_icon = 'PROPERTIES'
    CATEGORY_COLOR = (0.08, 0.26, 0.26)

    value: EnumProperty(name='Format', items=dxgi.FORMAT_ENUM_ITEMS,
                        default='R32G32B32_FLOAT')

    def init(self, context):
        super().init(context)
        self.add_output('BufferIOSocketFormat', 'Format')

    def evaluate(self, ctx):
        name = self.value if self.value in dxgi.SUPPORTED_FORMATS else 'R32G32B32_FLOAT'
        self.set_info([name])
        return {'Format': name}

    def draw_buttons(self, context, layout):
        layout.prop(self, 'value', text='')
        self.draw_info(layout)


class BUFFERIO_NODE_value_string(BufferIONode):
    bl_idname = 'BufferIOValueString'
    bl_label = 'String'
    bl_description = 'Output a string (can be wired into file path inputs of other nodes)'
    bl_icon = 'FONT_DATA'
    CATEGORY_COLOR = (0.28, 0.14, 0.28)

    value: StringProperty(name='String', default='')

    def init(self, context):
        super().init(context)
        self.add_output('BufferIOSocketString', 'String')

    def evaluate(self, ctx):
        text = self.value or ''
        display = text if len(text) <= 46 else text[:44] + '…'
        self.set_info([display or 'Empty string'])
        return {'String': text}

    def draw_buttons(self, context, layout):
        layout.prop(self, 'value', text='')
        self.draw_info(layout)


class BUFFERIO_NODE_value_float(BufferIONode):
    bl_idname = 'BufferIOValueFloat'
    bl_label = 'Float'
    bl_description = 'Output a float (e.g. the Scale of a Transform node)'
    bl_icon = 'DRIVER'
    CATEGORY_COLOR = (0.22, 0.22, 0.22)

    value: FloatProperty(name='Value', default=0.01)

    def init(self, context):
        super().init(context)
        self.add_output('BufferIOSocketFloat', 'Value')

    def evaluate(self, ctx):
        self.set_info([f'{self.value:g}'])
        return {'Value': float(self.value)}

    def draw_buttons(self, context, layout):
        layout.prop(self, 'value', text='')
        self.draw_info(layout)


class BUFFERIO_NODE_value_int(BufferIONode):
    bl_idname = 'BufferIOValueInt'
    bl_label = 'Int'
    bl_description = 'Output an integer (e.g. byte offset / count / stride)'
    bl_icon = 'LINENUMBERS_ON'
    CATEGORY_COLOR = (0.26, 0.26, 0.26)

    value: IntProperty(name='Value', default=0)

    def init(self, context):
        super().init(context)
        self.add_output('BufferIOSocketInt', 'Value')

    def evaluate(self, ctx):
        self.set_info([f'{int(self.value)}'])
        return {'Value': int(self.value)}

    def draw_buttons(self, context, layout):
        layout.prop(self, 'value', text='')
        self.draw_info(layout)


class BUFFERIO_NODE_value_bool(BufferIONode):
    bl_idname = 'BufferIOValueBool'
    bl_label = 'Bool'
    bl_description = 'Output a boolean (e.g. Mirror / Flip Winding / Flip UV)'
    bl_icon = 'CHECKBOX_HLT'
    CATEGORY_COLOR = (0.26, 0.16, 0.20)

    value: BoolProperty(name='Value', default=False)

    def init(self, context):
        super().init(context)
        self.add_output('BufferIOSocketBool', 'Value')

    def evaluate(self, ctx):
        self.set_info(['On' if self.value else 'Off'])
        return {'Value': bool(self.value)}

    def draw_buttons(self, context, layout):
        layout.prop(self, 'value', text='')
        self.draw_info(layout)


CLASSES = (
    BUFFERIO_NODE_value_format,
    BUFFERIO_NODE_value_string,
    BUFFERIO_NODE_value_float,
    BUFFERIO_NODE_value_int,
    BUFFERIO_NODE_value_bool,
)
