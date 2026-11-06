"""BufferIO 数据模型：PropertyGroup 定义、fmt 元素解析填充与属性更新回调。

元素集合既挂载在 Scene（侧面板）也挂载在 VB ELEMENT DESC 节点上，
解析填充逻辑（parse_fmt_elements）由两条路径共用。
"""

import re
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, IntProperty, StringProperty,
)

from . import dxgi
from . import fmt_parser
from .constants import ELEMENT_SEMANTIC_ITEMS, SEMANTIC_GUESS


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


def _apply_ib_format(target, format_name):
    """把 ib txt 里读到的格式写入元素/节点（不支持的格式保持原值）"""
    if format_name and format_name in dxgi.SUPPORTED_FORMATS:
        target.format = format_name


def _index_path_update(self, context):
    """INDEX 项选择 txt 路径后自动解析头部，填入 first index / index count / 格式"""
    if getattr(self, 'semantic', None) == 'INDEX':
        fp = self.filepath or getattr(self, 'source_file', '')
        if fp and Path(fp).suffix.lower() == '.txt':
            result = _parse_ib_header(fp)
            if result is not None:
                self.first_index, self.index_count, self.byte_offset = result[:3]
                _apply_ib_format(self, result[3])
    _push_element(self)


def _ib_txt_update(self, context):
    """选择 IB txt 路径后自动解析头部，填入 first index / index count / 格式"""
    result = _parse_ib_header(self.ib_txt)
    if result is not None:
        self.first_index, self.index_count, self.byte_offset = result[:3]
        _apply_ib_format(self, result[3])
    _push_element(self)


def _host_desc_node(elem):
    """元素所属的 VB ELEMENT DESC 节点。

    PropertyGroup 的 id_data 返回的是拥有它的节点树（Node 不是 ID），
    需要再按指针定位宿主节点；挂在 Scene 上的元素返回 None。
    """
    tree = elem.id_data
    if not isinstance(tree, bpy.types.NodeTree):
        return None
    pointer = elem.as_pointer()
    for node in tree.nodes:
        if node.bl_idname != 'BufferIOSourceFile':
            continue
        for item in node.elements:
            if item.as_pointer() == pointer:
                return node
    return None


def _push_element(self):
    """宿主为 VB ELEMENT DESC 节点时，把元素属性写入内部节点组"""
    node = _host_desc_node(self)
    if node is not None:
        from .nodes.element_desc import notify_element_changed
        notify_element_changed(node, self)


def _element_update(self, context):
    """元素属性变更：宿主为 VB ELEMENT DESC 节点时同步内部节点与输出端口"""
    node = _host_desc_node(self)
    if node is not None:
        from .nodes.element_desc import notify_element_changed
        notify_element_changed(node, self)


class BufferIOElement(bpy.types.PropertyGroup):
    """FMT 模式下解析出的元素条目"""
    # Blender 4.2+ 用 id 跟踪列表项身份，启用 template_list 原生多选/拖拽重排
    id: IntProperty(default=0, options={'HIDDEN'})
    enabled: BoolProperty(name='Enabled', default=True, update=_element_update)
    warning: IntProperty(name='Warning', default=0, min=0, max=2,
                         description='0 OK / 1 red (inconsistent stride or out of bounds) / 2 yellow (byte sum does not match stride)')
    name: StringProperty(name='Name')
    semantic_name: StringProperty(name='Semantic Name',
                                  description='Original semantic name (e.g. POSITION / TANGENT)')
    semantic: EnumProperty(name='Semantic', items=ELEMENT_SEMANTIC_ITEMS, default='SKIP',
                           update=_element_update)
    semantic_index: IntProperty(name='Semantic Index', min=0, default=0,
                                description='Original semantic index (e.g. the 5 in ATTRIBUTE 5)')
    index: IntProperty(name='Index', min=0, default=0,
                       description='Target Semantic Index (e.g. TEXCOORD 0-3), which determines the number of UV / color attributes',
                       update=_element_update)
    # 解析数据
    filepath: StringProperty(name='File Path', subtype='FILE_PATH',
                             update=_index_path_update,
                             description='Data file path (filled automatically when loading FMT, can be edited manually); Index Buffer entries may also point to an ib txt (parsed automatically)')
    ib_txt: StringProperty(name='IB txt', subtype='FILE_PATH',
                           update=_ib_txt_update,
                           description='3dmigoto FrameAnalysis ib txt (faces only). Lowest priority: used when there is no file path or first / count are not set')
    # INDEX 项的 first index / index count，默认 0 表示不启用偏移/限制
    first_index: IntProperty(name='first index', default=0, min=0,
                             update=_element_update,
                             description='First index offset; filled automatically from the txt header after selecting a path, can be edited manually')
    index_count: IntProperty(name='index count', default=0, min=0,
                             update=_element_update,
                             description='Index count; 0 = unlimited; filled automatically from the txt header after selecting a path, can be edited manually')
    count: IntProperty(name='Count', default=0, min=0,
                       update=_element_update,
                       description='Number of elements to read; 0 = unlimited (the end of the buffer may contain invalid data, so the read can be limited to the first N elements)')
    # 静态枚举（固定顺序，值不随语义变化而漂移）；默认值在创建元素/加载时显式写入
    format: EnumProperty(name='Format', items=dxgi.FORMAT_ENUM_ITEMS, default='R32G32B32_FLOAT',
                         update=_element_update)
    input_slot: IntProperty()
    offset: IntProperty(name='Element Offset', default=0,
                        update=_element_update,
                        description='Vertex attribute: byte offset of the element within the stride (AlignedByteOffset)')
    byte_offset: IntProperty(name='Byte Offset', min=0, default=0,
                             update=_element_update,
                             description='Start byte offset of the data in the buffer file; filled automatically from each txt header when loading FMT, can be edited manually')
    stride: IntProperty(name='Stride', default=0,
                        update=_element_update,
                        description='Byte stride per element; 0 = tight packing (equal to the format byte width)')
    source_file: StringProperty()


def _assign_id(collection, item):
    """为列表项分配唯一 id（Blender 4.2+ UIList 原生多选/拖拽重排依赖）"""
    existing = {i.id for i in collection if i != item}
    item.id = 1
    while item.id in existing:
        item.id += 1
    return item.id


# --- fmt 元素解析填充（侧面板加载与 VB ELEMENT DESC 节点共用） -------------

def _add_vertex_item(elements, element, stride, source_file, byte_offset=0):
    """把 fmt 顶点元素加入元素集合"""
    item = elements.add()
    _assign_id(elements, item)
    item.enabled = element.is_per_vertex
    # 语义名/索引由列表行内与属性面板显示，name 只保留缓冲槽位/偏移
    item.name = f'vb{element.input_slot} +{element.byte_offset}'
    item.semantic_name = element.semantic_name
    item.semantic = SEMANTIC_GUESS.get(element.semantic_name, 'SKIP')
    item.semantic_index = element.semantic_index
    # 目标索引默认与语义索引一致，可在属性面板中修改
    item.index = element.semantic_index
    if element.format in dxgi.SUPPORTED_FORMATS:
        item.format = element.format
    else:
        item.format = 'R32G32B32_FLOAT'  # 兜底：不支持的格式用常见顶点格式占位
    item.input_slot = element.input_slot
    item.offset = element.byte_offset
    item.byte_offset = byte_offset
    item.stride = stride
    item.source_file = source_file
    item.filepath = source_file
    return item


def _add_ib_item(elements, filepath, ib_txt, format_name, byte_offset):
    """把索引缓冲作为一个元素项加入集合（semantic=INDEX）

    filepath 为数据文件（buf）；first/vertex 与 ib_txt 从 txt 头部填充，
    读取优先级：文件路径+first/count -> 文件路径 -> ib txt。
    """
    item = elements.add()
    _assign_id(elements, item)
    item.enabled = True
    item.semantic_name = 'INDEX'
    item.semantic = 'INDEX'
    item.semantic_index = 0
    if format_name in dxgi.SUPPORTED_FORMATS:
        item.format = format_name
    else:
        item.format = 'R16_UINT'  # 兜底：不支持的格式用常见索引格式占位
    item.input_slot = -1
    item.offset = 0  # 索引无步长内偏移；文件起始偏移见 byte_offset
    item.byte_offset = byte_offset
    item.stride = 0  # 索引为紧凑数据
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
    """解析 .fmt / FrameAnalysis txt 并填充元素集合

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
