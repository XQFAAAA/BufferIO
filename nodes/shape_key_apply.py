"""形态键装配节点：把多组形态键数据附加到网格数据。

形态键输入使用几何节点式的长条多输入端口，可同时连接多组形态键资源，
按连线顺序依次追加（连锁处理）；端口允许为空，未连接时不报错。
与网格装配节点分离，装配只负责索引与顶点属性。
"""

from dataclasses import replace

from bpy.props import EnumProperty

from ..constants import ALGORITHM_ITEMS
from .base import BufferIONode
from .data import MeshData, ShapeKeyData
from .evaluator import active_links


class BUFFERIO_NODE_shape_key_apply(BufferIONode):
    bl_idname = 'BufferIOShapeKeyApply'
    bl_label = 'ShapeKey Assemble'
    bl_description = 'Append shape key groups to mesh data; the ShapeKey port accepts multiple links'
    bl_icon = 'SHAPEKEY_DATA'
    CATEGORY_COLOR = (0.30, 0.26, 0.08)

    # 形态键装配算法：当前仅「默认」，后续算法在 constants.ALGORITHM_ITEMS 追加
    algorithm: EnumProperty(name='Algorithm', items=ALGORITHM_ITEMS,
                            default='KEEP', description='Shape key algorithm')

    def init(self, context):
        super().init(context)
        self.add_input('BufferIOSocketMesh', 'Mesh')
        self.add_input('BufferIOSocketShapeKey', 'ShapeKey', multi_input=True)
        self.add_output('BufferIOSocketMesh', 'Mesh')

    def evaluate(self, ctx):
        mesh = ctx.input(self, 'Mesh')
        if not isinstance(mesh, MeshData):
            raise ValueError('Mesh input is not connected')
        groups = list(mesh.shape_keys)
        # 长条端口上的连线按顺序追加；空端口/禁用连线直接跳过
        for socket in self.inputs:
            if socket.bl_idname != 'BufferIOSocketShapeKey':
                continue
            for link in active_links(socket):
                shape_key = ctx.evaluate_node(link.from_node).get(
                    link.from_socket.name)
                if isinstance(shape_key, ShapeKeyData):
                    groups.append(shape_key)
        self.set_info([f'Shape Keys x{len(groups)}'])
        return {'Mesh': replace(mesh, shape_keys=groups)}

    def draw_buttons(self, context, layout):
        layout.prop(self, 'algorithm', text='')
        self.draw_info(layout)
