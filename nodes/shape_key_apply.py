"""形态键装配节点：按槽位把多组形态键数据附加到网格数据。

与网格装配节点一致，形态键端口按槽位创建（SHAPEKEY[i]），
可用节点上的 +/− 按钮增减数量；每组按连接顺序依次追加。
与网格装配节点分离，装配只负责索引与顶点属性。
"""

from dataclasses import replace

from bpy.props import EnumProperty, IntProperty

from ..constants import ALGORITHM_ITEMS
from .base import BufferIONode
from .data import MeshData, ShapeKeyData


class BUFFERIO_NODE_shape_key_apply(BufferIONode):
    bl_idname = 'BufferIOShapeKeyApply'
    bl_label = 'ShapeKey Assemble'
    bl_description = 'Append shape key groups to mesh data by slots'
    bl_icon = 'SHAPEKEY_DATA'
    CATEGORY_COLOR = (0.30, 0.26, 0.08)

    shape_count: IntProperty(name='Shape Key Slots', default=2, min=1, max=64)

    # 形态键装配算法：当前仅「默认」，后续算法在 constants.ALGORITHM_ITEMS 追加
    algorithm: EnumProperty(name='Algorithm', items=ALGORITHM_ITEMS,
                            default='KEEP', description='Shape key algorithm')

    def init(self, context):
        super().init(context)
        self._build_inputs()
        self.add_output('BufferIOSocketMesh', 'Mesh')

    def _build_inputs(self):
        self.add_input('BufferIOSocketMesh', 'Mesh')
        for i in range(self.shape_count):
            self.add_input('BufferIOSocketShapeKey', f'SHAPEKEY[{i}]')

    def rebuild_sockets(self):
        """按当前槽位数量重建输入端口，并保留仍然存在的连线

        连线按「Socket 类型 + 同类序号」记录，增减槽位时不会丢连线。
        """
        links = []
        counts = {}
        for socket in self.inputs:
            order = counts.get(socket.bl_idname, 0)
            counts[socket.bl_idname] = order + 1
            for link in socket.links:
                links.append((link.from_node.name, link.from_socket.name,
                              socket.bl_idname, order))
        while len(self.inputs):
            self.inputs.remove(self.inputs[0])
        self._build_inputs()

        tree = self.id_data
        groups = {}
        for socket in self.inputs:
            groups.setdefault(socket.bl_idname, []).append(socket)
        for from_node_name, from_socket_name, idname, order in links:
            targets = groups.get(idname, [])
            if order >= len(targets):
                continue
            source = tree.nodes.get(from_node_name)
            from_socket = source.outputs.get(from_socket_name) if source else None
            if from_socket is not None:
                tree.links.new(from_socket, targets[order])

    def evaluate(self, ctx):
        mesh = ctx.input(self, 'Mesh')
        if not isinstance(mesh, MeshData):
            raise ValueError('Mesh input is not connected')
        groups = list(mesh.shape_keys)
        for socket in self.inputs:
            if socket.bl_idname != 'BufferIOSocketShapeKey':
                continue
            data = ctx.input(self, socket.name)
            if isinstance(data, ShapeKeyData):
                groups.append(data)
        self.set_info([f'Shape Keys x{len(groups)}'])
        return {'Mesh': replace(mesh, shape_keys=groups)}

    def draw_buttons(self, context, layout):
        row = layout.row(align=True)
        op = row.operator('bufferio.assemble_slot', text='SHAPEKEY', icon='ADD')
        op.node_name = self.name
        op.delta = 1
        op = row.operator('bufferio.assemble_slot', text='SHAPEKEY', icon='REMOVE')
        op.node_name = self.name
        op.delta = -1

        layout.prop(self, 'algorithm', text='')
        self.draw_info(layout)
