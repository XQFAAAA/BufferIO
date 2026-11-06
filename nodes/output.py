"""导入节点：把节点图结果烘焙为 Blender 网格与骨架，按钮直接显示在节点上。

缩放/镜像/轴转换/环绕与 UV 翻转都在这里完成（不再需要单独的变换节点）；
骨骼矩阵直接连到本节点，只有矩阵时只导入骨架。
"""

import numpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import axis_conversion

from .. import buffer_io
from ..constants import AXIS_ITEMS
from ..core import build_and_link
from .base import BufferIONode
from .data import ArrayData, MeshData


class BUFFERIO_NODE_output_mesh(BufferIONode):
    bl_idname = 'BufferIOOutput'
    bl_label = 'Import'
    bl_description = 'Import mesh data and bone matrices into a Blender object or armature'
    bl_icon = 'OBJECT_DATA'
    CATEGORY_COLOR = (0.26, 0.16, 0.10)

    object_name: StringProperty(name='Object Name', default='BufferIO_Mesh')
    armature_name: StringProperty(name='Bone Name', default='')
    scale: FloatProperty(name='Scale', default=0.01, min=0.0001)
    mirror_x: BoolProperty(name='Mirror X', default=False)
    flip_winding: BoolProperty(name='Flip Winding', default=True)
    flip_texcoord_v: BoolProperty(name='Flip UV', default=True)
    axis_forward: EnumProperty(name='Forward', items=AXIS_ITEMS, default='Y')
    axis_up: EnumProperty(name='Up', items=AXIS_ITEMS, default='Z')

    # 未连接时在输入端口上直接编辑属性
    SOCKET_PROPERTIES = {
        'Object Name': 'object_name',
        'Bone Name': 'armature_name',
        'Scale': 'scale',
        'Mirror X': 'mirror_x',
        'Flip Winding': 'flip_winding',
        'Flip UV': 'flip_texcoord_v',
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

    def evaluate(self, ctx):
        mesh = ctx.input(self, 'Mesh')
        matrix = ctx.input(self, 'Matrix')
        if not isinstance(mesh, MeshData) and not isinstance(matrix, ArrayData):
            raise ValueError('Mesh and Matrix inputs are not connected')

        scale = float(self.input_value(ctx, 'Scale', self.scale))
        if scale < 0.0001:
            scale = 0.0001
        mirror_x = bool(self.input_value(ctx, 'Mirror X', self.mirror_x))
        flip_winding = bool(self.input_value(
            ctx, 'Flip Winding', self.flip_winding))
        flip_texcoord_v = bool(self.input_value(
            ctx, 'Flip UV', self.flip_texcoord_v))

        matrices = None
        if isinstance(matrix, ArrayData):
            matrices = numpy.ascontiguousarray(
                matrix.values, dtype=numpy.float32).reshape(-1, 3, 4)
        elif isinstance(mesh, MeshData) and mesh.bone_matrices is not None:
            matrices = mesh.bone_matrices

        name = self.input_string(ctx, 'Object Name', self.object_name) or 'BufferIO_Mesh'
        bone_name = self.input_string(ctx, 'Bone Name', self.armature_name)

        conversion = axis_conversion(
            from_forward=self.axis_forward, from_up=self.axis_up,
            to_forward='-Y', to_up='Z').to_4x4()

        # 只有矩阵：只导入骨架，不建网格
        if not isinstance(mesh, MeshData):
            if matrices is None or not len(matrices):
                raise ValueError('Matrix data is empty')
            collection = ctx.context.collection or ctx.context.scene.collection
            arm = buffer_io.build_armature(
                bone_name or name, matrices,
                scale=scale, mirror_x=mirror_x, conversion=conversion,
                collection=collection)
            self.set_info([arm.name, f'Bones {len(arm.data.bones)}'])
            return {'Object': arm}

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
            f'UV {len(data.uv_layers)}  Shape Keys {max(len(data.shape_keys.key_blocks) - 1, 0) if data.shape_keys else 0}',
        ])
        return {'Object': obj}

    def draw_buttons(self, context, layout):
        # 对象名/骨骼名/缩放/翻转已并入输入端口，这里只保留坐标轴选择
        row = layout.row(align=True)
        row.prop(self, 'axis_forward', text='')
        row.prop(self, 'axis_up', text='')
        op = layout.operator('bufferio.node_bake', text='Import', icon='IMPORT')
        op.node_name = self.name
        self.draw_info(layout)
