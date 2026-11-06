"""骨骼矩阵节点：从骨骼矩阵缓冲读取蒙皮矩阵。"""

import bpy
import numpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from .. import buffer_io, dxgi
from ..constants import BONE_MATRIX_ALGORITHM_ITEMS
from .base import BufferIONode
from .data import ArrayData


class BUFFERIO_NODE_bone_matrix(BufferIONode):
    bl_idname = 'BufferIOBoneMatrix'
    bl_label = 'Bone Matrix'
    bl_description = 'Read a bone 3x4 skinning matrix buffer (e.g. vs-cb4)'
    bl_icon = 'BONE_DATA'
    CATEGORY_COLOR = (0.30, 0.12, 0.12)

    filepath: StringProperty(name='File', subtype='FILE_PATH')
    format: EnumProperty(name='Format', items=dxgi.FORMAT_ENUM_ITEMS,
                         default='MATRIX3X4_FLOAT')
    stride: IntProperty(name='Stride', default=0, min=0,
                        description='0 = packed (equal to the format byte width)')
    byte_offset: IntProperty(name='Byte Offset', default=0, min=0)
    count: IntProperty(name='Count', default=0, min=0,
                       description='0 = unlimited')
    # 矩阵解码算法：默认保持；正交矩阵模式跳过旋转非正交的骨骼
    algorithm: EnumProperty(name='Algorithm', items=BONE_MATRIX_ALGORITHM_ITEMS,
                            default='KEEP', description='Bone matrix decoding algorithm')

    # 未连接时在输入端口上直接编辑属性
    SOCKET_PROPERTIES = {
        'File': 'filepath',
        'Format': 'format',
        'Stride': 'stride',
        'Byte Offset': 'byte_offset',
        'Count': 'count',
    }

    def init(self, context):
        super().init(context)
        # 输入端：已连接时优先于节点属性
        self.add_input('BufferIOSocketString', 'File')
        self.add_input('BufferIOSocketFormat', 'Format')
        self.add_input('BufferIOSocketInt', 'Stride')
        self.add_input('BufferIOSocketInt', 'Byte Offset')
        self.add_input('BufferIOSocketInt', 'Count')
        self.add_output('BufferIOSocketBoneMatrix', 'Matrix')

    def evaluate(self, ctx):
        filepath = self.input_string(ctx, 'File', self.filepath)
        if not filepath:
            raise ValueError('No bone matrix file specified')
        format_name = self.input_value(ctx, 'Format', self.format)
        if format_name not in dxgi.SUPPORTED_FORMATS:
            format_name = self.format
        stride = max(int(self.input_value(ctx, 'Stride', self.stride) or 0), 0)
        byte_offset = max(int(self.input_value(ctx, 'Byte Offset', self.byte_offset) or 0), 0)
        count = max(int(self.input_value(ctx, 'Count', self.count) or 0), 0)

        array, fmt = buffer_io.read_buffer(
            bpy.path.abspath(filepath), format_name, stride=stride,
            offset=byte_offset, limit=count)
        matrices = fmt.to_float(array).reshape(-1, 3, 4)
        info = [f'Bone Matrices x{len(matrices)}', format_name]
        if self.algorithm == 'ORTHOGONAL':
            skipped = self._skip_non_orthogonal(matrices)
            info.append(f'Orthogonal skipped {skipped}')
        self.set_info(info)
        return {'Matrix': ArrayData(matrices, 'BONEMATRIX', 0, format_name)}

    @staticmethod
    def _skip_non_orthogonal(matrices):
        """把旋转非正交的矩阵清零：数组位置不变（编号不跳过），骨架创建时跳过这些槽位"""
        rot = numpy.asarray(matrices[:, :3, :3], dtype=numpy.float64)
        products = rot @ rot.transpose(0, 2, 1)
        valid = numpy.isclose(products, numpy.eye(3), atol=1e-3).all(axis=(1, 2))
        matrices[~valid] = 0.0
        return int((~valid).sum())

    def draw_buttons(self, context, layout):
        # 文件/格式/偏移/数量已并入输入端口
        layout.prop(self, 'algorithm', text='')
        self.draw_info(layout)
