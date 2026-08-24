"""BufferIO 操作符：列表增删移动、校验、预设/语义、资源发现与导入。"""

import json
import re
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import buffer_io
from . import dxgi
from . import fmt_parser
from .constants import (
    ELEMENT_SEMANTIC_ITEMS,
    SEMANTICS_DIR,
    SEMANTIC_GUESS,
    _semantics_items,
)
from .core import (
    build_and_link,
    collect_vertex_arrays,
    validate_entries,
)
from .properties import _assign_id, _auto_export_name


class BUFFERIO_OT_element_add(bpy.types.Operator):
    bl_idname = 'bufferio.element_add'
    bl_label = '添加元素'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        elems = context.scene.bufferio_elements
        item = elems.add()
        _assign_id(elems, item)
        item.enabled = True
        item.name = '自定义元素'
        item.format = 'R32G32B32_FLOAT'
        context.scene.bufferio_elements_index = len(elems) - 1
        return {'FINISHED'}


class BUFFERIO_OT_element_remove(bpy.types.Operator):
    bl_idname = 'bufferio.element_remove'
    bl_label = '移除元素'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        elems = scene.bufferio_elements
        index = scene.bufferio_elements_index
        if 0 <= index < len(elems):
            elems.remove(index)
            scene.bufferio_elements_index = min(index, len(elems) - 1)
        return {'FINISHED'}


class BUFFERIO_OT_element_move(bpy.types.Operator):
    bl_idname = 'bufferio.element_move'
    bl_label = '移动元素'
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name='方向', items=(('UP', '上', ''), ('DOWN', '下', '')))

    def execute(self, context):
        scene = context.scene
        elems = scene.bufferio_elements
        index = scene.bufferio_elements_index
        if self.direction == 'UP' and index > 0:
            elems.move(index, index - 1)
            scene.bufferio_elements_index = index - 1
        elif self.direction == 'DOWN' and index < len(elems) - 1:
            elems.move(index, index + 1)
            scene.bufferio_elements_index = index + 1
        return {'FINISHED'}


class BUFFERIO_OT_validate_all(bpy.types.Operator):
    """手动触发步长/偏移校验，高亮异常列表项（仅提示不影响导入）"""
    bl_idname = 'bufferio.validate_all'
    bl_label = '校验步长/偏移'
    bl_options = {'REGISTER'}

    def execute(self, context):
        result = validate_entries(context.scene.bufferio_elements)
        self.report({'INFO'},
                    f'校验完成：ERROR {result["red"]} 项（步长不一致/越界/语义冲突），'
                    f'QUESTION {result["yellow"]} 项（偏移布局不连续）')
        if result['missing']:
            self.report({'WARNING'}, f'缺少必需语义：{", ".join(result["missing"])}')
        return {'FINISHED'}


class BUFFERIO_OT_save_semantics(bpy.types.Operator):
    """把当前 FMT 模式元素配置保存为预设（不含文件路径）"""
    bl_idname = 'bufferio.save_semantics'
    bl_label = '保存预设'
    bl_options = {'REGISTER'}

    name: StringProperty(name='预设名称', default='')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'name')
        layout.label(text=f'保存位置：{SEMANTICS_DIR}')

    def execute(self, context):
        name = self.name.strip()
        if not name:
            self.report({'ERROR'}, '请输入预设名称')
            return {'CANCELLED'}
        preset = []
        for e in context.scene.bufferio_elements:
            preset.append({
                'name': e.name,
                'enabled': e.enabled,
                'semantic_name': e.semantic_name,
                'semantic': e.semantic,
                'semantic_index': e.semantic_index,
                'index': e.index,
                'format': e.format,
                'input_slot': e.input_slot,
                'offset': e.offset,
                'stride': e.stride,
                'count': e.count,
            })
        try:
            SEMANTICS_DIR.mkdir(parents=True, exist_ok=True)
            with open(SEMANTICS_DIR / f'{name}.json', 'w', encoding='utf-8') as f:
                json.dump(preset, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.report({'ERROR'}, f'保存失败: {exc}')
            return {'CANCELLED'}
        self.report({'INFO'}, f'已保存 {len(preset)} 个元素预设：{name}')
        return {'FINISHED'}


class BUFFERIO_OT_load_semantics(bpy.types.Operator):
    """从插件本地加载 FMT 元素预设并重建元素列表（不含文件路径）"""
    bl_idname = 'bufferio.load_semantics'
    bl_label = '加载预设'
    bl_options = {'REGISTER', 'UNDO'}

    scheme: EnumProperty(name='预设', items=_semantics_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'scheme')

    def execute(self, context):
        if not self.scheme:
            self.report({'ERROR'}, '没有可用的预设')
            return {'CANCELLED'}
        try:
            with open(SEMANTICS_DIR / f'{self.scheme}.json', 'r', encoding='utf-8') as f:
                preset = json.load(f)
        except Exception as exc:
            self.report({'ERROR'}, f'读取失败: {exc}')
            return {'CANCELLED'}
        if not isinstance(preset, list):
            self.report({'ERROR'}, f'预设格式不兼容（旧版语义方案？）：{self.scheme}')
            return {'CANCELLED'}

        valid_sem = {i[0] for i in ELEMENT_SEMANTIC_ITEMS}
        valid_fmt = {i[0] for i in dxgi.format_enum_items()}
        elems = context.scene.bufferio_elements
        # 保留现有文件路径，加载预设后按索引恢复（预设本身不含路径）
        old_paths = [(e.filepath, e.ib_txt) for e in elems]
        elems.clear()
        for i, d in enumerate(preset):
            e = elems.add()
            _assign_id(elems, e)
            e.enabled = bool(d.get('enabled', True))
            e.name = d.get('name', d.get('label', ''))
            e.semantic_name = d.get('semantic_name', '')
            if d.get('semantic') in valid_sem:
                e.semantic = d['semantic']
            e.semantic_index = int(d.get('semantic_index', 0))
            e.index = int(d.get('index', 0))
            if d.get('format') in valid_fmt:
                e.format = d['format']
            elif not e.format:
                e.format = 'R32G32B32_FLOAT'  # 预设无有效格式时兜底
            e.input_slot = int(d.get('input_slot', 0))
            e.offset = int(d.get('offset', 0))
            e.stride = int(d.get('stride', 0))
            e.count = int(d.get('count', 0))
            if i < len(old_paths):
                e.filepath = old_paths[i][0]
                e.ib_txt = old_paths[i][1]
        context.scene.bufferio_elements_index = 0
        self.report({'INFO'}, f'已加载 {len(elems)} 个元素预设：{self.scheme}')
        return {'FINISHED'}


def wuwa_shapekey_map(directory, prefix, report=None):
    """wuwa 形态键路径映射：

    1. 取同前缀 vb6 的 hash（如 000017-vb6=3c20751d-... -> 3c20751d）；
    2. 搜索同时含该 hash 与形态键 CS hash 的文件（如 000003-u0=3c20751d-cs=...），
       得到形态键 draw call id 列表；
    3. 按 draw call id 排序，返回 {slot: {语义: 文件路径}}（最多两份）。

    report 为可选回调（如 operator.report），用于输出警告/信息；返回 None 表示未找到。
    """
    cs_hash = '9bf4420c82102011'  # 鸣潮形态键 compute shader hash（固定）

    def warn(msg):
        if report is not None:
            report({'WARNING'}, msg)

    # 1. 同前缀 vb6 -> hash
    vb6_matches = sorted(directory.glob(f'{prefix}-vb6=*.buf'))
    if not vb6_matches:
        warn('wuwa：未找到同前缀 vb6 文件')
        return None
    m = re.search(r'-vb6=([0-9a-f]+)-', vb6_matches[0].name)
    if not m:
        warn('wuwa：无法从 vb6 文件名提取 hash')
        return None
    vb6_hash = m.group(1)

    # 2. 定位形态键 draw call id
    draw_ids = set()
    for f in directory.glob('*-cs=*.buf'):
        if vb6_hash in f.name and cs_hash in f.name:
            m2 = re.match(r'^(\d+)-', f.name)
            if m2:
                draw_ids.add(m2.group(1))
    if not draw_ids:
        warn(f'wuwa：未找到 hash {vb6_hash} 对应的形态键 CS 调用')
        return None

    # 3. 每个 draw call 的 cs-cb0/cs-t0/cs-t1 -> 语义
    sem_map = {
        'cs-cb0': 'SHAPEKEY_OFFSET',
        'cs-t0': 'SHAPEKEY_VERTEXID',
        'cs-t1': 'SHAPEKEY_VERTEXOFFSET',
    }
    result = {}
    for slot, draw_id in enumerate(sorted(draw_ids)):
        if slot >= 2:
            break  # 目前只支持两份形态键
        entry = {}
        for tag, semantic in sem_map.items():
            matches = sorted(directory.glob(f'{draw_id}-{tag}=*.buf'))
            if matches:
                entry[semantic] = matches[0]
        if entry:
            result[slot] = entry
    if not result:
        warn('wuwa：未找到形态键 CS 数据文件')
        return None
    if report is not None:
        report({'INFO'}, f'wuwa：vb6 hash {vb6_hash}，形态键 draw {sorted(draw_ids)}')
    return result


class BUFFERIO_OT_load_fmt(bpy.types.Operator):
    bl_idname = 'bufferio.load_fmt'
    bl_label = '加载 FMT'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.fmt;*.txt;*.buf', options={'HIDDEN'})
    shapekey_mode: EnumProperty(
        name='形态键搜索',
        items=[
            ('NONE', '无', '不进行形态键搜索'),
            ('WUWA', 'wuwa', '鸣潮：通过同前缀 vb6 定位形态键 CS 调用，并自动添加 SHAPEKEY 元素'),
        ],
        default='NONE',
    )
    bone_matrix_tag: StringProperty(
        name='骨骼矩阵',
        description='填写资源 tag（如 vs-cb4），加载后自动搜索同 draw call 的骨骼矩阵并添加 BONEMATRIX 元素',
        default='',
    )
    fill_paths_by_tag: BoolProperty(
        name='按tag填路径',
        description='勾选后不解析布局，仅按文件名前缀自动填充元素文件路径（无需 txt 头部，支持直接选择 .buf）；元素需已存在（可手动添加或加载语义预设）',
        default=False,
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene
        scene.bufferio_fmt_path = self.filepath
        fmt_path = Path(bpy.path.abspath(self.filepath))

        if not fmt_path.is_file():
            self.report({'ERROR'}, f'FMT 文件不存在: {fmt_path}')
            return {'CANCELLED'}

        # 按tag填路径：不解析布局，仅按前缀填充已有元素的路径
        if self.fill_paths_by_tag:
            return self._fill_paths_by_tag(context, fmt_path)

        try:
            fmt = fmt_parser.parse_fmt_file(fmt_path)
            resources = fmt_parser.discover_resources(fmt_path)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        scene.bufferio_elements.clear()

        if resources.kind == 'FMT':
            # WWMI 风格：所有元素在同一个 vb 中，步长为头部 stride
            vb_path = str(resources.vb_files[0])
            # 索引缓冲项置顶
            self._add_ib_element(scene, str(resources.ib_data), '',
                                 fmt.ib_format, fmt.byte_offset)
            for element in fmt.elements:
                self._add_element(scene, element, fmt.stride, vb_path,
                                  fmt.byte_offset)
            scene.bufferio_ib_file = str(resources.ib_data)
            scene.bufferio_ib_format = fmt.ib_format
            scene.bufferio_ib_offset = fmt.byte_offset
            scene.bufferio_ib_first = 0
            scene.bufferio_ib_count = 0
            info = (f'已加载：first index 0，index count 整个缓冲，'
                    f'步长 {fmt.stride}')
        else:
            # FrameAnalysis 风格：按 InputSlot 分组，步长取组内最大元素末端
            slot_strides = {}
            for element in fmt.elements:
                if not element.is_per_vertex:
                    continue
                try:
                    byte_width = dxgi.DXGIFormat(element.format).byte_width
                except dxgi.FormatError as e:
                    self.report({'ERROR'}, str(e))
                    return {'CANCELLED'}
                end = element.byte_offset + byte_width
                slot_strides[element.input_slot] = max(
                    slot_strides.get(element.input_slot, 0), end)

            # 解析 ib txt 头部，索引缓冲项置顶
            ib_fmt = fmt_parser.parse_fmt_file(resources.ib_txt)
            self._add_ib_element(scene, str(resources.ib_data), str(resources.ib_txt),
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
                    self.report({'ERROR'},
                                f'找不到 InputSlot {element.input_slot} 对应的 vb 文件')
                    return {'CANCELLED'}
                self._add_element(scene, element,
                                  slot_strides[element.input_slot], str(vb_path),
                                  slot_offsets.get(element.input_slot, 0))
            scene.bufferio_ib_file = str(resources.ib_data)
            scene.bufferio_ib_format = ib_fmt.ib_format
            scene.bufferio_ib_offset = ib_fmt.byte_offset
            scene.bufferio_ib_first = ib_fmt.first_index
            scene.bufferio_ib_count = ib_fmt.index_count
            info = (f'已加载：first index {ib_fmt.first_index}，'
                    f'index count {ib_fmt.index_count}，'
                    f'顶点数 {fmt.vertex_count}')

        scene.bufferio_fmt_info = info
        result = validate_entries(scene.bufferio_elements)
        if result['missing']:
            self.report({'WARNING'}, f'缺少必需语义：{", ".join(result["missing"])}')

        # wuwa 形态键搜索：自动添加并填入 SHAPEKEY 元素
        if self.shapekey_mode == 'WUWA':
            dash = fmt_path.name.find('-')
            if dash <= 0:
                self.report({'WARNING'}, 'wuwa：无法从 FMT 文件名识别 FrameAnalysis 前缀')
            else:
                mapping = wuwa_shapekey_map(fmt_path.parent, fmt_path.name[:dash],
                                            self.report)
                if mapping:
                    # 形态键数据默认格式（可手动调整）
                    default_format = {
                        'SHAPEKEY_OFFSET': 'R32_UINT',
                        'SHAPEKEY_VERTEXID': 'R32_UINT',
                        'SHAPEKEY_VERTEXOFFSET': 'R16G16B16_FLOAT',
                    }
                    added = 0
                    for slot in sorted(mapping):
                        for semantic, p in mapping[slot].items():
                            item = scene.bufferio_elements.add()
                            _assign_id(scene.bufferio_elements, item)
                            item.enabled = True
                            item.semantic_name = semantic
                            item.semantic = semantic
                            item.semantic_index = slot
                            item.index = slot
                            if default_format.get(semantic) in dxgi.SUPPORTED_FORMATS:
                                item.format = default_format[semantic]
                            item.name = f'{semantic} {slot}'
                            item.filepath = str(p)
                            added += 1
                    self.report({'INFO'}, f'wuwa 形态键：已添加 {added} 个元素')

        # 骨骼矩阵：填写 tag（如 vs-cb4）后自动查找同 draw call 的骨骼矩阵
        tag = self.bone_matrix_tag.strip()
        if tag:
            dash = fmt_path.name.find('-')
            if dash <= 0:
                self.report({'WARNING'}, '无法从 FMT 文件名识别 FrameAnalysis 前缀')
            else:
                prefix = fmt_path.name[:dash]
                matches = sorted(fmt_path.parent.glob(f'{prefix}-{tag}=*.buf'))
                if not matches:
                    self.report({'WARNING'}, f'未找到骨骼矩阵：{prefix}-{tag}=*.buf')
                else:
                    item = scene.bufferio_elements.add()
                    _assign_id(scene.bufferio_elements, item)
                    item.enabled = True
                    item.semantic_name = 'BONEMATRIX'
                    item.semantic = 'BONEMATRIX'
                    item.index = 0
                    if 'MATRIX3X4_FLOAT' in dxgi.SUPPORTED_FORMATS:
                        item.format = 'MATRIX3X4_FLOAT'
                    item.stride = 0
                    item.offset = 0
                    item.filepath = str(matches[0])
                    auto = _auto_export_name(str(matches[0]))
                    item.name = auto if auto else tag
                    self.report({'INFO'}, f'骨骼矩阵：{matches[0].name}')

        self.report({'INFO'}, info)
        return {'FINISHED'}

    @staticmethod
    def _add_element(scene, element, stride, source_file, byte_offset=0):
        item = scene.bufferio_elements.add()
        _assign_id(scene.bufferio_elements, item)
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

    @staticmethod
    def _add_ib_element(scene, filepath, ib_txt, format_name, byte_offset):
        """把索引缓冲作为一个元素项加入列表（semantic=INDEX）

        filepath 为数据文件（buf）；first/vertex 与 ib_txt 从 txt 头部填充，
        读取优先级：文件路径+first/count -> 文件路径 -> ib txt。
        """
        item = scene.bufferio_elements.add()
        _assign_id(scene.bufferio_elements, item)
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

    def _fill_paths_by_tag(self, context, fmt_path):
        """按资源 tag 自动填充已有元素的文件路径（不解析布局，无需 txt 头部）

        从所选文件名提取前缀，扫描同前缀资源，按 input_slot 填入 vb 槽位、
        按 INDEX 语义填入 ib；并同步解析对应 txt 头部的 byte offset / first / count。
        元素需已存在（手动添加或加载语义预设），不清空、不重建元素列表。
        """
        prefix = fmt_path.name.split('-', 1)[0]
        if '-' not in fmt_path.name or not prefix:
            self.report({'ERROR'}, '无法从文件名识别 FrameAnalysis 前缀')
            return {'CANCELLED'}

        found = {}
        for f in sorted(fmt_path.parent.glob(f'{prefix}-*')):
            if not f.is_file():
                continue
            rest = f.name[len(prefix) + 1:]
            tag = rest.split('=', 1)[0]
            if tag:
                found.setdefault(tag, []).append(f)

        def fill(element):
            """按元素的槽位/语义匹配资源 tag，返回是否填入"""
            if element.semantic == 'INDEX' or element.input_slot == -1:
                tag = 'ib'
            elif element.input_slot >= 0:
                tag = f'vb{element.input_slot}'
            else:
                return False
            candidates = found.get(tag)
            if not candidates:
                return False
            buf = next((p for p in candidates if p.suffix.lower() == '.buf'),
                       candidates[0])
            txt = next((p for p in candidates if p.suffix.lower() == '.txt'), None)
            element.filepath = str(buf)
            if txt is not None:
                try:
                    header = fmt_parser.parse_fmt_file(txt)
                    if tag == 'ib':
                        element.ib_txt = str(txt)
                        element.first_index = header.first_index
                        element.index_count = header.index_count
                    element.byte_offset = header.byte_offset
                except Exception:
                    pass
            return True

        applied = sum(1 for e in context.scene.bufferio_elements
                      if e.enabled and fill(e))

        # wuwa 形态键：按语义+索引填入 SHAPEKEY 元素
        extra = 0
        if self.shapekey_mode == 'WUWA':
            mapping = wuwa_shapekey_map(fmt_path.parent, prefix, self.report)
            if mapping:
                for slot, sem_map in mapping.items():
                    for semantic, p in sem_map.items():
                        for e in context.scene.bufferio_elements:
                            if e.enabled and e.semantic == semantic \
                                    and e.index == slot:
                                e.filepath = str(p)
                                extra += 1
                                break

        self.report({'INFO'},
                    f'前缀 {prefix}：找到 {len(found)} 类资源，已填入 {applied} 项路径'
                    + (f'，wuwa 形态键 {extra} 项' if extra else ''))
        return {'FINISHED'}


class BUFFERIO_OT_import_fmt(bpy.types.Operator):
    bl_idname = 'bufferio.import_fmt'
    bl_label = '导入（FMT 模式）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        elements = [e for e in scene.bufferio_elements
                    if e.enabled and e.semantic != 'SKIP']
        if not elements:
            self.report({'ERROR'}, '没有启用的元素，请先加载 FMT 文件')
            return {'CANCELLED'}

        result = validate_entries(scene.bufferio_elements)
        if result['missing']:
            self.report({'WARNING'}, f'缺少必需语义：{", ".join(result["missing"])}')
        try:
            # 索引缓冲（INDEX 项）与顶点属性统一由元素列表收集
            faces, arrays = collect_vertex_arrays(elements)
            if faces is None and scene.bufferio_ib_file:
                # 兜底：元素列表中无 INDEX 项时使用独立索引设置
                if Path(scene.bufferio_ib_file).suffix.lower() == '.txt':
                    faces = buffer_io.read_indices_from_ib_txt(scene.bufferio_ib_file)
                else:
                    faces = buffer_io.read_indices(
                        scene.bufferio_ib_file, scene.bufferio_ib_format,
                        offset=scene.bufferio_ib_offset,
                        first=scene.bufferio_ib_first, count=scene.bufferio_ib_count)

            # 网格名取 INDEX 文件名；骨架名优先取 BONEMATRIX 元素文件名（骨骼矩阵文件）
            index_path = next(
                (e.filepath or e.ib_txt for e in elements
                 if e.semantic == 'INDEX' and (e.filepath or e.ib_txt)), None)
            if not index_path and scene.bufferio_ib_file:
                index_path = scene.bufferio_ib_file
            mesh_name = Path(index_path).name if index_path \
                else (Path(scene.bufferio_fmt_path).stem or 'BufferIO_FMT')
            bone_path = next(
                (e.filepath for e in elements
                 if e.semantic == 'BONEMATRIX' and e.filepath), None)
            arm_name = Path(bone_path).name if bone_path \
                else (Path(scene.bufferio_fmt_path).name or None)

            obj = build_and_link(
                context, mesh_name, faces, arrays,
                scene.bufferio_flip_winding, scene.bufferio_flip_texcoord_v,
                scale=scene.bufferio_global_scale,
                mirror_x=scene.bufferio_mirror_x,
                axis_forward=scene.bufferio_axis_forward,
                axis_up=scene.bufferio_axis_up,
                armature_name=arm_name)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'},
                    f'导入完成：{len(obj.data.vertices)} 顶点，{len(obj.data.polygons)} 面')
        return {'FINISHED'}


CLASSES = (
    BUFFERIO_OT_element_add,
    BUFFERIO_OT_element_remove,
    BUFFERIO_OT_element_move,
    BUFFERIO_OT_validate_all,
    BUFFERIO_OT_save_semantics,
    BUFFERIO_OT_load_semantics,
    BUFFERIO_OT_load_fmt,
    BUFFERIO_OT_import_fmt,
)
