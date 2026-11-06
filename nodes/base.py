"""BufferIO 节点基类：Socket 创建辅助、节点分类配色与信息展示。"""

import bpy

from .sockets import new_input, new_output


class BufferIONode(bpy.types.Node):
    bl_icon = 'NODETREE'
    # 分类配色（RGBA，写入节点自定义颜色）
    CATEGORY_COLOR = (0.16, 0.20, 0.26)
    # 默认宽度（默认 140 太窄，端口内的属性控件显示不全）
    bl_width_default = 240
    bl_width_min = 200

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == 'BufferIONodeTree'

    def init(self, context):
        """子类在此创建输入/输出 Socket"""
        self.use_custom_color = True
        self.color = self.CATEGORY_COLOR

    def evaluate(self, ctx):
        """返回 {输出 Socket 名称: 数据}；异常由求值器捕获。"""
        return {}

    def draw_buttons(self, context, layout):
        """子类可覆盖，绘制节点上的控件"""
        self.draw_info(layout)

    # --- Socket 创建辅助（自动设置颜色对应的形状） ---
    def add_input(self, idname, name, multi_input=False):
        return new_input(self, idname, name, multi_input)

    def add_output(self, idname, name):
        return new_output(self, idname, name)

    # --- 输入取值辅助（已连接的输入端口优先于节点属性） ---
    def input_socket(self, name):
        for socket in self.inputs:
            if socket.name == name:
                return socket
        return None

    def input_value(self, ctx, name, default):
        """输入端口已连接时取上游值，否则返回属性默认值"""
        socket = self.input_socket(name)
        if socket is None or not socket.is_linked:
            return default
        value = ctx.input(self, name)
        return default if value is None else value

    def input_string(self, ctx, name, default):
        """取字符串输入（已连接则用上游值），未设置时返回空字符串"""
        value = self.input_value(ctx, name, default)
        return str(value) if value else ''

    def disconnect_inputs(self, names):
        """断开这些输入端口上的连线（自动解析后避免外部值覆盖解析结果）"""
        tree = self.id_data
        for name in names:
            socket = self.input_socket(name)
            if socket is None:
                continue
            for link in list(socket.links):
                tree.links.remove(link)

    # --- 节点信息（上一次求值的结果摘要，保存在节点自定义属性里） ---
    def set_info(self, lines):
        self['info'] = '\n'.join(str(line) for line in lines if line)

    def draw_info(self, layout):
        text = self.get('info')
        if not text:
            return
        column = layout.column(align=True)
        column.scale_y = 0.78
        for line in str(text).split('\n'):
            column.label(text=line)
