"""IndexBuffer 节点：读取三角形索引缓冲（buf / ib txt），输出索引数据。

读取优先级与侧面板 IndexBuffer 元素一致：
文件路径+first/count -> 文件路径（自动分辨类型）-> ib txt。

txt 路径只作为节点属性（自动解析入口），不设输入端口；
解析成功后断开「格式 / 偏移」等输入连线，让解析结果生效。
"""

from pathlib import Path
from types import SimpleNamespace

import bpy
from bpy.props import EnumProperty, StringProperty

from .. import dxgi
from ..constants import ALGORITHM_ITEMS
from ..core import _read_index_entry
from ..properties import _parse_ib_header
from .base import BufferIONode
from .data import ArrayData

# 自动解析会覆盖这些属性，因此解析后断开它们的输入连线
PARSED_INPUTS = ('Format', 'Byte Offset', 'First Index', 'Index Count')


def _update_ib_txt(self, context):
    """选择 ib txt 后自动解析头部，填入 first index / index count / byte offset / 格式"""
    if self.get('cloning'):
        return  # 节点克隆期间不触发解析
    result = _parse_ib_header(self.ib_txt)
    if result is not None:
        self.set_socket_default('First Index', result[0])
        self.set_socket_default('Index Count', result[1])
        self.set_socket_default('Byte Offset', result[2])
        if result[3] and result[3] in dxgi.SUPPORTED_FORMATS:
            self.set_socket_default('Format', result[3])
        self.disconnect_inputs(PARSED_INPUTS)


class BUFFERIO_NODE_index_buffer(BufferIONode):
    bl_idname = 'BufferIOIndexBuffer'
    bl_label = 'Index Buffer'
    bl_description = 'Read a triangle index buffer (ib buf / ib txt)'
    bl_icon = 'MOD_TRIANGULATE'
    CATEGORY_COLOR = (0.30, 0.18, 0.05)

    ib_txt: StringProperty(name='IB txt', subtype='FILE_PATH', default='',
                           update=_update_ib_txt,
                           description='3dmigoto FrameAnalysis ib txt; the header is parsed automatically on selection')
    # 索引解码算法：当前仅「保持」，后续算法在 constants.ALGORITHM_ITEMS 追加
    algorithm: EnumProperty(name='Algorithm', items=ALGORITHM_ITEMS,
                            default='KEEP', description='Index decoding algorithm')

    # 覆盖输入 socket 的类默认值（仅列出与 socket 类默认不同的项）
    SOCKET_DEFAULTS = {
        'Format': 'R16_UINT',
    }

    def init(self, context):
        super().init(context)
        # 输入端：已连接时优先于 socket 默认值（txt 自动解析不设输入）
        self.add_input('BufferIOSocketFile', 'File')
        self.add_input('BufferIOSocketFormat', 'Format')
        self.add_input('BufferIOSocketInt', 'Byte Offset')
        self.add_input('BufferIOSocketInt', 'First Index')
        self.add_input('BufferIOSocketInt', 'Index Count')
        self.add_input('BufferIOSocketInt', 'Count')
        self.add_output('BufferIOSocketIndex', 'Index')
        self.init_socket_defaults()

    def evaluate(self, ctx):
        filepath = self.input_string(ctx, 'File')
        format_name = self.input_value(ctx, 'Format')
        byte_offset = max(int(self.input_value(ctx, 'Byte Offset') or 0), 0)
        first = max(int(self.input_value(ctx, 'First Index') or 0), 0)
        index_count = max(int(self.input_value(ctx, 'Index Count') or 0), 0)
        count = max(int(self.input_value(ctx, 'Count') or 0), 0)

        if not filepath and not self.ib_txt:
            raise ValueError('No index file path set')
        # 索引缓冲只允许 R16_UINT / R32_UINT（D3D 的 IA 索引格式），txt 不受格式限制
        if (filepath and Path(filepath).suffix.lower() != '.txt'
                and format_name not in dxgi.INDEX_FORMATS):
            raise ValueError(
                f'Index format must be {" / ".join(dxgi.INDEX_FORMATS)} (current: {format_name})')

        entry = SimpleNamespace(
            semantic='INDEX', format=format_name, first_index=first,
            index_count=index_count, count=count, byte_offset=byte_offset,
            offset=0, ib_txt=self.ib_txt)
        faces = _read_index_entry(entry, bpy.path.abspath(filepath))
        self.set_info([f'Index Buffer x{len(faces)}  {format_name}'])
        return {'Index': ArrayData(faces, 'INDEX', 0, format_name)}

    def draw_buttons(self, context, layout):
        # 仅保留没有输入端口的 txt 自动解析入口
        layout.prop(self, 'ib_txt', text='txt')
        layout.prop(self, 'algorithm', text='')
        self.draw_info(layout)
