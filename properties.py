"""BufferIO 数据模型：PropertyGroup 定义与属性更新回调。"""

import re
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, IntProperty, StringProperty,
)

from . import dxgi
from . import fmt_parser
from .constants import ELEMENT_SEMANTIC_ITEMS


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
    """解析 ib txt 头部，返回 (first_index, index_count, byte_offset)；失败返回 None"""
    if not filepath or not Path(filepath).is_file():
        return None
    try:
        fmt = fmt_parser.parse_fmt_file(Path(filepath))
    except Exception:
        return None
    return fmt.first_index, fmt.index_count, fmt.byte_offset


def _index_path_update(self, context):
    """INDEX 项选择 txt 路径后自动解析头部，填入 first index / index count"""
    if getattr(self, 'semantic', None) != 'INDEX':
        return
    fp = self.filepath or getattr(self, 'source_file', '')
    if not fp or Path(fp).suffix.lower() != '.txt':
        return
    result = _parse_ib_header(fp)
    if result is not None:
        self.first_index, self.index_count, self.byte_offset = result


def _ib_txt_update(self, context):
    """选择 IB txt 路径后自动解析头部，填入 first index / index count / byte offset"""
    result = _parse_ib_header(self.ib_txt)
    if result is not None:
        self.first_index, self.index_count, self.byte_offset = result


class BufferIOElement(bpy.types.PropertyGroup):
    """FMT 模式下解析出的元素条目"""
    # Blender 4.2+ 用 id 跟踪列表项身份，启用 template_list 原生多选/拖拽重排
    id: IntProperty(default=0, options={'HIDDEN'})
    enabled: BoolProperty(name='启用', default=True)
    warning: IntProperty(name='警告', default=0, min=0, max=2,
                         description='0 正常 / 1 红色（步长不一致或越界）/ 2 黄色（字节总和不等于步长）')
    name: StringProperty(name='名称')
    semantic_name: StringProperty(name='语义名',
                                  description='原始语义名（如 POSITION / TANGENT）')
    semantic: EnumProperty(name='属性', items=ELEMENT_SEMANTIC_ITEMS, default='SKIP')
    semantic_index: IntProperty(name='SemanticIndex', min=0, default=0,
                                description='原始语义索引（如 ATTRIBUTE 5 的 5）')
    index: IntProperty(name='索引', min=0, default=0,
                       description='目标语义索引（如 TEXCOORD 0-3），决定 UV/颜色等属性的编号')
    # 解析数据
    filepath: StringProperty(name='文件路径', subtype='FILE_PATH',
                             update=_index_path_update,
                             description='数据文件路径（加载 FMT 时自动填充，可手动修改）；INDEX 项可指向 ib txt（自动解析）')
    ib_txt: StringProperty(name='IB txt', subtype='FILE_PATH',
                           update=_ib_txt_update,
                           description='3dmigoto FrameAnalysis 的 ib txt（仅面索引）。优先级最低：无文件路径或未设 first/count 时使用')
    # INDEX 项的 first index / index count，默认 0 表示不启用偏移/限制
    first_index: IntProperty(name='first index', default=0, min=0,
                             description='首个索引偏移；选择 txt 路径后自动从头部填入，可手动修改')
    index_count: IntProperty(name='index count', default=0, min=0,
                             description='索引数量；0 = 不限制，选择 txt 路径后自动从头部填入，可手动修改')
    count: IntProperty(name='数量', default=0, min=0,
                       description='读取元素数量；0 = 不限制（缓冲末尾可能存在无效数据，可限制只读前 N 个）')
    # 静态枚举（固定顺序，值不随语义变化而漂移）；默认值在创建元素/加载时显式写入
    format: EnumProperty(name='格式', items=dxgi.FORMAT_ENUM_ITEMS, default='R32G32B32_FLOAT')
    input_slot: IntProperty()
    offset: IntProperty(name='偏移', default=0,
                        description='顶点属性：元素在步长内的字节偏移（AlignedByteOffset）')
    byte_offset: IntProperty(name='byte offset', min=0, default=0,
                             description='数据在缓冲文件中的起始字节偏移；加载 FMT 时从各 txt 头部自动填入，可手动修改')
    stride: IntProperty(name='步长', default=0,
                        description='每个元素的字节步长，0 = 紧凑（等于格式字节宽度）')
    source_file: StringProperty()


def _assign_id(collection, item):
    """为列表项分配唯一 id（Blender 4.2+ UIList 原生多选/拖拽重排依赖）"""
    existing = {i.id for i in collection if i != item}
    item.id = 1
    while item.id in existing:
        item.id += 1
    return item.id
