"""BufferIO 节点基类：Socket 创建辅助、socket 默认值与信息展示。"""

import bpy

from .sockets import new_input, new_output


class BufferIONode(bpy.types.Node):
    bl_icon = 'NODETREE'
    # 分类配色（RGBA，写入节点自定义颜色；是否启用由树的 use_category_color 决定）
    CATEGORY_COLOR = (0.16, 0.20, 0.26)
    # 默认宽度（默认 140 太窄，端口内的属性控件显示不全）
    bl_width_default = 240
    bl_width_min = 200

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == 'BufferIONodeTree'

    def init(self, context):
        """子类在此创建输入/输出 Socket，创建完成后调用 init_socket_defaults()"""
        # 分类配色为可选项（树级开关），默认与原生节点一致跟随主题
        if self.id_data is not None and self.id_data.use_category_color:
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

    # --- Socket 默认值（未连接输入的值的唯一来源，与原生 socket 一致） ---
    def init_socket_defaults(self):
        """按子类的 SOCKET_DEFAULTS（socket 名 -> 值）覆盖输入 socket 默认值
        （在子类 init 创建完 socket 后调用）"""
        for socket_name, value in getattr(self, 'SOCKET_DEFAULTS', {}).items():
            self.set_socket_default(socket_name, value)

    def set_socket_default(self, socket_name, value):
        """设置未连接输入的 socket 默认值（程序化建节点的写入入口）"""
        socket = self.input_socket(socket_name)
        if socket is not None and socket.bl_rna.properties.get('default_value') is not None:
            socket.default_value = value

    # --- 输入取值辅助（上游连线 -> socket 默认值） ---
    def input_socket(self, name):
        for socket in self.inputs:
            if socket.name == name:
                return socket
        return None

    def input_value(self, ctx, name):
        """输入端口取值：已连接取上游值，未连接取 socket 默认值"""
        socket = self.input_socket(name)
        if socket is not None and socket.is_linked:
            value = ctx.input(self, name)
            if value is not None:
                return value
        if socket is not None and socket.bl_rna.properties.get('default_value') is not None:
            return socket.default_value
        return None

    def input_string(self, ctx, name):
        """取字符串输入，未设置时返回空字符串"""
        value = self.input_value(ctx, name)
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
