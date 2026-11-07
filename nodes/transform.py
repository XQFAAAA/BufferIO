"""导入节点：把节点图结果烘焙为 Blender 网格与骨架，按钮直接显示在节点上。

缩放/镜像/轴转换以及环绕 / UV 翻转都在这里完成；骨骼矩阵直接连到本节点，
只有矩阵时只导入骨架。网格与骨架名称由输入端口指定，
FrameAnalysis 批量导入时按 ib txt 的 first index 顺序写成 Component 0、Component 1……
"""

import numpy
from bpy.props import EnumProperty
from bpy_extras.io_utils import axis_conversion

from .. import buffer_io
from ..constants import AXIS_ITEMS
from ..core import build_and_link
from .base import BufferIONode
from .data import ArrayData, MeshData


class BUFFERIO_NODE_import(BufferIONode):
    bl_idname = 'BufferIOImport'
    bl_label = 'Import'
    bl_description = ('Import mesh data and bone matrices into a Blender object '
                      'or armature')
    bl_icon = 'OBJECT_DATA'
    CATEGORY_COLOR = (0.26, 0.16, 0.10)

    axis_forward: EnumProperty(name='Forward', items=AXIS_ITEMS, default='Y')
    axis_up: EnumProperty(name='Up', items=AXIS_ITEMS, default='Z')

    # 覆盖输入 socket 的类默认值（仅列出与 socket 类默认不同的项）
    SOCKET_DEFAULTS = {
        'Object Name': 'Component 0',
        'Bone Name': '',
        'Scale': 0.01,
        'Mirror X': True,
        'Flip Winding': True,
        'Flip UV': True,
    }

    def init(self, context):
        super().init(context)
        self.add_input('BufferIOSocketMesh', 'Mesh')
        self.add_input('BufferIOSocketBoneMatrix', 'Matrix')
        self.add_input('BufferIOSocketString', 'Object Name')
        self.add_input('BufferIOSocketString', 'Bone Name')
        self.add_input('BufferIOSocketFloat', 'Scale')
        self.add_input('BufferIOSocketBool', 'Mirror X')
        self.add_input('BufferIOSocketBool', 'Flip Winding')
        self.add_input('BufferIOSocketBool', 'Flip UV')
        self.init_socket_defaults()

    def evaluate(self, ctx):
        mesh = ctx.input(self, 'Mesh')
        matrix = ctx.input(self, 'Matrix')
        if not isinstance(mesh, MeshData) and not isinstance(matrix, ArrayData):
            raise ValueError('Mesh and Matrix inputs are not connected')

        scale = max(float(self.input_value(ctx, 'Scale') or 0.0), 0.0001)
        mirror_x = bool(self.input_value(ctx, 'Mirror X'))
        flip_winding = bool(self.input_value(ctx, 'Flip Winding'))
        flip_texcoord_v = bool(self.input_value(ctx, 'Flip UV'))

        matrices = None
        if isinstance(matrix, ArrayData):
            matrices = numpy.ascontiguousarray(
                matrix.values, dtype=numpy.float32).reshape(-1, 3, 4)
        elif isinstance(mesh, MeshData) and mesh.bone_matrices is not None:
            matrices = mesh.bone_matrices

        name = self.input_string(ctx, 'Object Name') or 'Component 0'
        bone_name = self.input_string(ctx, 'Bone Name')

        conversion = axis_conversion(
            from_forward=self.axis_forward, from_up=self.axis_up,
            to_forward='-Y', to_up='Z').to_4x4()

        # 只有矩阵：只导入骨架，不建网格
        if not isinstance(mesh, MeshData):
            if matrices is None or not len(matrices):
                raise ValueError('Matrix data is empty')
            collection = ctx.context.collection or ctx.context.scene.collection
            arm = buffer_io.build_armature(
                bone_name or f'{name}_Armature', matrices,
                scale=scale, mirror_x=mirror_x, conversion=conversion,
                collection=collection)
            self.set_info([arm.name, f'Bones {len(arm.data.bones)}'])
            return {}

        obj = build_and_link(
            ctx.context, name,
            mesh.faces, mesh.arrays,
            flip_winding=flip_winding, flip_texcoord_v=flip_texcoord_v,
            scale=scale, mirror_x=mirror_x,
            axis_forward=self.axis_forward, axis_up=self.axis_up,
            armature_name=bone_name or None,
            shape_keys=([(group.offsets, group.vertex_ids,
                          group.vertex_offsets)
                         for group in mesh.shape_keys]
                        or None),
            bone_matrices=matrices,
            vertex_map=mesh.vertex_map)

        data = obj.data
        self.set_info([
            obj.name,
            f'Vertices {len(data.vertices)}  Faces {len(data.polygons)}',
            f'UV {len(data.uv_layers)}  Shape Keys '
            f'{max(len(data.shape_keys.key_blocks) - 1, 0) if data.shape_keys else 0}',
        ])
        return {}

    def draw_buttons(self, context, layout):
        # 名称/缩放/翻转已并入输入端口，这里只保留坐标轴选择
        row = layout.row(align=True)
        row.prop(self, 'axis_forward', text='')
        row.prop(self, 'axis_up', text='')
        op = layout.operator('bufferio.node_bake', text='Import', icon='IMPORT')
        op.node_name = self.name
        self.draw_info(layout)
