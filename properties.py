"""FMT 元素解析：把 fmt / FrameAnalysis 文本解析成轻量元素对象。

解析结果只用于节点侧栏的「从 FMT 导入」：生成 Vertex Buffer / Index Buffer
节点与节点框，因此不再依赖 PropertyGroup，也不需要属性更新回调。
"""

import re
from pathlib import Path

from . import dxgi
from . import fmt_parser
from .constants import SEMANTIC_GUESS


def _auto_export_name(filepath):
    """从 3dmigoto FrameAnalysis 文件名推导导出名称（如 vb0 / vs-cb4 / cs-cb0）

    文件名形如 `000056-vb0=15fb50a9-vs=...buf`、
    `000056-vs-cb4=f02baf77-vs=...buf` 或
    `000003-cs-cb0=06450352-cs=...buf`，
    提取 draw id 后的第一个 `-名称=hash-` 段；匹配不到返回空字符串。
    """
    if not filepath:
        return ''
    name = Path(filepath).name
    m = re.match(r'^\d+-([A-Za-z0-9][A-Za-z0-9-]*)=[0-9a-fA-F]+-', name)
    if m:
        return m.group(1)
    return ''


def _parse_ib_header(filepath):
    """解析 ib txt 头部，返回 (first_index, index_count, byte_offset, 格式)；失败返回 None"""
    if not filepath or not Path(filepath).is_file():
        return None
    try:
        fmt = fmt_parser.parse_fmt_file(Path(filepath))
    except Exception:
        return None
    return fmt.first_index, fmt.index_count, fmt.byte_offset, fmt.ib_format


class ElementData:
    """解析出的单个元素（顶点属性或索引缓冲）"""

    def __init__(self):
        self.enabled = True
        self.name = ''
        self.semantic_name = ''
        self.semantic = 'SKIP'
        self.semantic_index = 0
        self.index = 0
        self.filepath = ''
        self.ib_txt = ''
        self.first_index = 0
        self.index_count = 0
        self.count = 0
        self.format = 'R32G32B32_FLOAT'
        self.input_slot = 0
        self.offset = 0
        self.byte_offset = 0
        self.stride = 0
        self.source_file = ''


class ElementList(list):
    """兼容 parse_fmt_elements 的填充接口（add() 追加一个 ElementData）"""

    def add(self):
        item = ElementData()
        self.append(item)
        return item


def _add_vertex_item(elements, element, stride, source_file, byte_offset=0):
    """把 fmt 顶点元素加入元素列表"""
    item = elements.add()
    item.enabled = element.is_per_vertex
    item.name = f'vb{element.input_slot} +{element.byte_offset}'
    item.semantic_name = element.semantic_name
    item.semantic = SEMANTIC_GUESS.get(element.semantic_name, 'SKIP')
    item.semantic_index = element.semantic_index
    item.index = element.semantic_index
    if element.format in dxgi.SUPPORTED_FORMATS:
        item.format = element.format
    else:
        # 兜底：不支持的格式用常见顶点格式占位
        item.format = 'R32G32B32_FLOAT'
    item.input_slot = element.input_slot
    item.offset = element.byte_offset
    item.byte_offset = byte_offset
    item.stride = stride
    item.source_file = source_file
    item.filepath = source_file
    return item


def _add_ib_item(elements, filepath, ib_txt, format_name, byte_offset):
    """把索引缓冲作为一个元素加入列表（semantic=INDEX）"""
    item = elements.add()
    item.enabled = True
    item.semantic_name = 'INDEX'
    item.semantic = 'INDEX'
    item.semantic_index = 0
    if format_name in dxgi.SUPPORTED_FORMATS:
        item.format = format_name
    else:
        # 兜底：不支持的格式用常见索引格式占位
        item.format = 'R16_UINT'
    item.input_slot = -1
    item.offset = 0
    item.byte_offset = byte_offset
    item.stride = 0
    item.filepath = filepath
    item.name = 'ib'
    # 从 ib txt 头部填充 first index / index count，并保留 txt 作为兜底
    if ib_txt and Path(ib_txt).is_file():
        item.ib_txt = ib_txt
        try:
            fmt = fmt_parser.parse_fmt_file(Path(ib_txt))
            item.first_index = fmt.first_index
            item.index_count = fmt.index_count
        except Exception:
            pass
    return item


def parse_fmt_elements(elements, fmt_path):
    """解析 .fmt / FrameAnalysis txt 并填充元素列表

    返回 (info, ib_settings)；失败抛出异常，由调用方决定如何呈现。
    ib_settings: {'file', 'format', 'offset', 'first', 'count'}
    """
    fmt = fmt_parser.parse_fmt_file(fmt_path)
    resources = fmt_parser.discover_resources(fmt_path)
    elements.clear()

    if resources.kind == 'FMT':
        # WWMI 风格：所有元素在同一个 vb 中，步长为头部 stride
        vb_path = str(resources.vb_files[0])
        _add_ib_item(elements, str(resources.ib_data), '',
                     fmt.ib_format, fmt.byte_offset)
        for element in fmt.elements:
            _add_vertex_item(elements, element, fmt.stride, vb_path,
                             fmt.byte_offset)
        ib_settings = {'file': str(resources.ib_data),
                       'format': fmt.ib_format, 'offset': fmt.byte_offset,
                       'first': 0, 'count': 0}
        info = f'Loaded: first index 0, index count whole buffer, stride {fmt.stride}'
    else:
        # FrameAnalysis 风格：按 InputSlot 分组，步长取组内最大元素末端
        slot_strides = {}
        for element in fmt.elements:
            if not element.is_per_vertex:
                continue
            byte_width = dxgi.DXGIFormat(element.format).byte_width
            end = element.byte_offset + byte_width
            slot_strides[element.input_slot] = max(
                slot_strides.get(element.input_slot, 0), end)

        # 解析 ib txt 头部，索引缓冲项置顶
        ib_fmt = fmt_parser.parse_fmt_file(resources.ib_txt)
        _add_ib_item(elements, str(resources.ib_data), str(resources.ib_txt),
                     ib_fmt.ib_format, ib_fmt.byte_offset)

        # 解析各 vb 槽位 txt 头部，得到每槽位数据在缓冲文件中的起始字节偏移
        slot_offsets = {}
        for slot, vb_txt in resources.vb_txt_files.items():
            try:
                slot_offsets[slot] = fmt_parser.parse_fmt_file(vb_txt).byte_offset
            except Exception:
                pass

        for element in fmt.elements:
            if not element.is_per_vertex:
                continue
            vb_path = resources.vb_files.get(element.input_slot)
            if vb_path is None:
                raise ValueError(
                    f'No vb file found for InputSlot {element.input_slot}')
            _add_vertex_item(elements, element,
                             slot_strides[element.input_slot], str(vb_path),
                             slot_offsets.get(element.input_slot, 0))
        ib_settings = {'file': str(resources.ib_data),
                       'format': ib_fmt.ib_format, 'offset': ib_fmt.byte_offset,
                       'first': ib_fmt.first_index, 'count': ib_fmt.index_count}
        info = (f'Loaded: first index {ib_fmt.first_index}, '
                f'index count {ib_fmt.index_count}, vertex count {fmt.vertex_count}')

    return info, ib_settings
