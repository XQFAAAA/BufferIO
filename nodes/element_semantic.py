"""Vertex Buffer 节点：按文件 + 格式 + 步长读取任意顶点缓冲，并标注语义。

原“通用缓冲 / Buffer Semantic”节点，现作为 VB ELEMENT DESC 节点组的内部元素节点：
一个节点对应一个缓冲属性（或索引缓冲走 IndexBuffer 节点），输出 ArrayData。
"""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from .. import buffer_io, dxgi
from ..constants import ALGORITHM_ITEMS as BASE_ALGORITHM_ITEMS
from ..constants import ELEMENT_SEMANTIC_ITEMS, FLOAT_SEMANTICS
from .base import BufferIONode
from .data import ArrayData

# Vertex Buffer 不处理索引（索引请用 Index Buffer 节点），
# 也不处理分离的形态键分段数据与骨骼矩阵（分别用 Shape Key / Bone Matrix 节点）
EXCLUDED_SEMANTICS = {
    'SKIP', 'INDEX',
    'SHAPEKEY_OFFSET', 'SHAPEKEY_VERTEXID', 'SHAPEKEY_VERTEXOFFSET',
    'BONEMATRIX',
}
BUFFER_SEMANTIC_ITEMS = [
    item for item in ELEMENT_SEMANTIC_ITEMS if item[0] not in EXCLUDED_SEMANTICS
]

# 顶点解码算法：默认 = 按格式规范解码（法线保留八面体解码），终末地 = 八面体法线算法
ALGORITHM_ITEMS = BASE_ALGORITHM_ITEMS + [
    ('ENDFIELD', 'Endfield', 'Octahedral normal algorithm (normals only); also switches the format to R10G10B10A2'),
]


def _update_algorithm(self, context):
    """法线选择终末地算法时同步把格式改为 R10G10B10A2（并断开格式输入连线）"""
    if self.get('cloning'):
        return
    if self.algorithm == 'ENDFIELD' and self.semantic == 'NORMAL':
        self.format = 'R10G10B10A2_UNORM'
        self.disconnect_inputs(('Format',))


class BUFFERIO_NODE_element_semantic(BufferIONode):
    bl_idname = 'BufferIOGenericBuffer'  # 沿用旧 idname，兼容已保存的节点树
    bl_label = 'Vertex Buffer'
    bl_description = ('Read an arbitrary vertex buffer (file + format + stride/offset) '
                      'and tag a target semantic; serves as the inner element node '
                      'of the VB ELEMENT DESC node group')
    bl_icon = 'FILE_CACHE'
    CATEGORY_COLOR = (0.13, 0.20, 0.30)

    filepath: StringProperty(name='File', subtype='FILE_PATH')
    format: EnumProperty(name='Format', items=dxgi.FORMAT_ENUM_ITEMS,
                         default='R32G32B32_FLOAT')
    stride: IntProperty(name='Stride', default=0, min=0,
                        description='0 = packed (equal to the format byte width)')
    byte_offset: IntProperty(name='Byte Offset', default=0, min=0)
    elem_offset: IntProperty(name='Element Offset', default=0, min=0)
    count: IntProperty(name='Count', default=0, min=0,
                       description='0 = unlimited')
    semantic: EnumProperty(name='Semantic', items=BUFFER_SEMANTIC_ITEMS,
                           default='POSITION')
    semantic_index: IntProperty(name='Semantic Index', default=0, min=0)
    algorithm: EnumProperty(name='Algorithm', items=ALGORITHM_ITEMS,
                            default='KEEP', update=_update_algorithm,
                            description='Vertex decoding algorithm; Endfield also switches the format to R10G10B10A2')

    # 未连接时在输入端口上直接编辑属性
    SOCKET_PROPERTIES = {
        'File': 'filepath',
        'Format': 'format',
        'Stride': 'stride',
        'Byte Offset': 'byte_offset',
        'Element Offset': 'elem_offset',
        'Count': 'count',
    }

    def init(self, context):
        super().init(context)
        # 输入端：已连接时优先于节点属性
        self.add_input('BufferIOSocketString', 'File')
        self.add_input('BufferIOSocketFormat', 'Format')
        self.add_input('BufferIOSocketInt', 'Stride')
        self.add_input('BufferIOSocketInt', 'Byte Offset')
        self.add_input('BufferIOSocketInt', 'Element Offset')
        self.add_input('BufferIOSocketInt', 'Count')
        self.add_output('BufferIOSocketArray', 'Array')

    def evaluate(self, ctx):
        filepath = self.input_string(ctx, 'File', self.filepath)
        if not filepath:
            raise ValueError('No buffer file specified')
        format_name = self.input_value(ctx, 'Format', self.format)
        if format_name not in dxgi.SUPPORTED_FORMATS:
            format_name = self.format
        stride = max(int(self.input_value(ctx, 'Stride', self.stride) or 0), 0)
        byte_offset = max(int(self.input_value(ctx, 'Byte Offset', self.byte_offset) or 0), 0)
        elem_offset = max(int(self.input_value(ctx, 'Element Offset', self.elem_offset) or 0), 0)
        count = max(int(self.input_value(ctx, 'Count', self.count) or 0), 0)

        array, fmt = buffer_io.read_buffer(
            bpy.path.abspath(filepath), format_name, stride=stride,
            offset=byte_offset, elem_offset=elem_offset,
            limit=count)
        if self._octahedral(fmt):
            # 八面体法线解码属于语义层约定（终末地/保持），不写进格式层
            array = dxgi.decode_octahedral_10bit(array)
        elif self.semantic in FLOAT_SEMANTICS:
            array = fmt.to_float(array)
        self.set_info([
            f'{self.semantic}{self.semantic_index or ""}  {format_name}',
            f'{len(array)} entries  stride {fmt.byte_width}'
            + ('  Endfield' if self.algorithm == 'ENDFIELD' else ''),
        ])
        return {'Array': ArrayData(
            array, self.semantic, self.semantic_index, format_name,
            bpy.path.abspath(filepath))}

    def _octahedral(self, fmt):
        """法线且为 R10G10B10A2 打包格式时使用八面体解码"""
        return (self.semantic == 'NORMAL' and fmt.packed
                and fmt.name.startswith('R10G10B10A2'))

    def draw_buttons(self, context, layout):
        # 文件/格式/偏移/数量已并入输入端口，这里只保留语义与算法
        row = layout.row(align=True)
        row.prop(self, 'semantic', text='')
        row.prop(self, 'semantic_index', text='')
        # 算法对所有语义都显示（终末地 = 八面体解码 + R10G10B10A2，仅法线生效）
        layout.prop(self, 'algorithm', text='')
        self.draw_info(layout)
