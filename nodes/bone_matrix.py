"""骨骼矩阵节点：从骨骼矩阵缓冲读取蒙皮矩阵。"""

import bpy
import numpy
from bpy.props import EnumProperty

from .. import buffer_io
from ..constants import BONE_MATRIX_ALGORITHM_ITEMS
from .base import BufferIONode
from .data import ArrayData


class BUFFERIO_NODE_bone_matrix(BufferIONode):
    bl_idname = 'BufferIOBoneMatrix'
    bl_label = 'Bone Matrix'
    bl_description = 'Read a bone 3x4 skinning matrix buffer (e.g. vs-cb4)'
    bl_icon = 'BONE_DATA'
    CATEGORY_COLOR = (0.30, 0.12, 0.12)

    # 矩阵解码算法：默认保持；正交矩阵模式跳过旋转非正交的骨骼
    algorithm: EnumProperty(name='Algorithm', items=BONE_MATRIX_ALGORITHM_ITEMS,
                            default='KEEP', description='Bone matrix decoding algorithm')

    # 覆盖输入 socket 的类默认值（仅列出与 socket 类默认不同的项）
    SOCKET_DEFAULTS = {
        'Format': 'MATRIX3X4_FLOAT',
    }

    def init(self, context):
        super().init(context)
        # 输入端：已连接时优先于 socket 默认值
        self.add_input('BufferIOSocketFile', 'File')
        self.add_input('BufferIOSocketFormat', 'Format')
        self.add_input('BufferIOSocketInt', 'Stride')
        self.add_input('BufferIOSocketInt', 'Byte Offset')
        self.add_input('BufferIOSocketInt', 'Count')
        self.add_output('BufferIOSocketBoneMatrix', 'Matrix')
        self.init_socket_defaults()

    def evaluate(self, ctx):
        filepath = self.input_string(ctx, 'File')
        if not filepath:
            raise ValueError('No bone matrix file specified')
        format_name = self.input_value(ctx, 'Format')
        stride = max(int(self.input_value(ctx, 'Stride') or 0), 0)
        byte_offset = max(int(self.input_value(ctx, 'Byte Offset') or 0), 0)
        count = max(int(self.input_value(ctx, 'Count') or 0), 0)

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
