"""形态键节点：读取一组分段形态键数据（边界 / 顶点 id / 位移向量）。"""

import bpy
import numpy
from bpy.props import EnumProperty

from .. import buffer_io
from ..constants import ALGORITHM_ITEMS
from .base import BufferIONode
from .data import ShapeKeyData


class BUFFERIO_NODE_shape_key(BufferIONode):
    bl_idname = 'BufferIOShapeKey'
    bl_label = 'ShapeKey Resource'
    bl_description = 'Read a set of segmented shape key data (e.g. wuwa cs-cb0 / cs-t0 / cs-t1)'
    bl_icon = 'SHAPEKEY_DATA'
    CATEGORY_COLOR = (0.30, 0.26, 0.08)

    # 形态键解码算法：当前仅「保持」，后续算法在 constants.ALGORITHM_ITEMS 追加
    algorithm: EnumProperty(name='Algorithm', items=ALGORITHM_ITEMS,
                            default='KEEP', description='Shape key decoding algorithm')

    # 覆盖输入 socket 的类默认值（仅列出与 socket 类默认不同的项）
    SOCKET_DEFAULTS = {
        'Offsets Format': 'R32_UINT',
        'IDs Format': 'R32_UINT',
        'Vectors Format': 'R16G16B16_FLOAT',
    }

    def init(self, context):
        super().init(context)
        # 输入端：已连接时优先于 socket 默认值
        self.add_input('BufferIOSocketFile', 'Offsets File')
        self.add_input('BufferIOSocketFile', 'IDs File')
        self.add_input('BufferIOSocketFile', 'Vectors File')
        self.add_input('BufferIOSocketFormat', 'Offsets Format')
        self.add_input('BufferIOSocketFormat', 'IDs Format')
        self.add_input('BufferIOSocketFormat', 'Vectors Format')
        self.add_output('BufferIOSocketShapeKey', 'ShapeKey')
        self.init_socket_defaults()

    def evaluate(self, ctx):
        offsets_file = self.input_string(ctx, 'Offsets File')
        ids_file = self.input_string(ctx, 'IDs File')
        vecs_file = self.input_string(ctx, 'Vectors File')
        if not (offsets_file and ids_file and vecs_file):
            raise ValueError('All three shape key data files must be specified')

        offsets_format = self.input_value(ctx, 'Offsets Format')
        ids_format = self.input_value(ctx, 'IDs Format')
        vecs_format = self.input_value(ctx, 'Vectors Format')

        offsets = self._read_flat(offsets_file, offsets_format)
        vertex_ids = self._read_flat(ids_file, ids_format)

        array, fmt = buffer_io.read_buffer(
            bpy.path.abspath(vecs_file), vecs_format)
        vertex_offsets = numpy.ascontiguousarray(
            fmt.to_float(array).reshape(-1, 3), dtype=numpy.float32)

        self.set_info([
            f'Shape Keys x{max(len(offsets) - 1, 0)}',
            f'Vertex IDs {len(vertex_ids)}  Vectors {len(vertex_offsets)}',
        ])
        return {'ShapeKey': ShapeKeyData(
            offsets=offsets, vertex_ids=vertex_ids,
            vertex_offsets=vertex_offsets)}

    @staticmethod
    def _read_flat(filepath, format_name):
        array, _ = buffer_io.read_buffer(bpy.path.abspath(filepath), format_name)
        return numpy.ascontiguousarray(array.reshape(-1))

    def draw_buttons(self, context, layout):
        # 三个文件与格式已并入输入端口
        layout.prop(self, 'algorithm', text='')
        self.draw_info(layout)
