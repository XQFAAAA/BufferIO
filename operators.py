"""BufferIO 操作符：列表增删移动、校验、预设/语义、资源发现与导入。"""

import json
from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty

from . import buffer_io
from . import dxgi
from . import fmt_parser
from .constants import (
    ATTRIBUTE_SEMANTIC_ITEMS,
    ELEMENT_SEMANTIC_ITEMS,
    INDEXED_SEMANTICS,
    MESH_PRESETS_DIR,
    SEMANTICS_DIR,
    SEMANTIC_GUESS,
    _mesh_preset_items,
    _semantics_items,
)
from .core import (
    build_and_link,
    collect_vertex_arrays,
    validate_entries,
)
from .properties import _assign_id


class BUFFERIO_OT_attribute_add(bpy.types.Operator):
    bl_idname = 'bufferio.attribute_add'
    bl_label = '添加属性'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        attrs = context.scene.bufferio_attributes
        item = attrs.add()
        _assign_id(attrs, item)
        context.scene.bufferio_attributes_index = len(attrs) - 1
        return {'FINISHED'}


class BUFFERIO_OT_attribute_remove(bpy.types.Operator):
    bl_idname = 'bufferio.attribute_remove'
    bl_label = '移除属性'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        attrs = scene.bufferio_attributes
        index = scene.bufferio_attributes_index
        if 0 <= index < len(attrs):
            attrs.remove(index)
            scene.bufferio_attributes_index = min(index, len(attrs) - 1)
        return {'FINISHED'}


class BUFFERIO_OT_attribute_move(bpy.types.Operator):
    bl_idname = 'bufferio.attribute_move'
    bl_label = '移动属性'
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name='方向', items=(('UP', '上', ''), ('DOWN', '下', '')))

    def execute(self, context):
        scene = context.scene
        attrs = scene.bufferio_attributes
        index = scene.bufferio_attributes_index
        if self.direction == 'UP' and index > 0:
            attrs.move(index, index - 1)
            scene.bufferio_attributes_index = index - 1
        elif self.direction == 'DOWN' and index < len(attrs) - 1:
            attrs.move(index, index + 1)
            scene.bufferio_attributes_index = index + 1
        return {'FINISHED'}


class BUFFERIO_OT_element_add(bpy.types.Operator):
    bl_idname = 'bufferio.element_add'
    bl_label = '添加元素'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        elems = context.scene.bufferio_elements
        item = elems.add()
        _assign_id(elems, item)
        item.enabled = True
        item.label = '自定义元素'
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
        scene = context.scene
        if scene.bufferio_mode == 'MESH':
            entries = scene.bufferio_attributes
        else:
            entries = scene.bufferio_elements
        result = validate_entries(entries)
        self.report({'INFO'},
                    f'校验完成：ERROR {result["red"]} 项（步长不一致/越界/语义冲突），'
                    f'QUESTION {result["yellow"]} 项（偏移布局不连续）')
        if result['missing']:
            self.report({'WARNING'}, f'缺少必需语义：{", ".join(result["missing"])}')
        return {'FINISHED'}


class BUFFERIO_OT_save_semantics(bpy.types.Operator):
    """把当前元素的语义映射（SemanticName SemanticIndex -> 属性）保存到插件本地"""
    bl_idname = 'bufferio.save_semantics'
    bl_label = 'Save Semantics'
    bl_options = {'REGISTER'}

    name: StringProperty(name='方案名称', default='')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'name')
        layout.label(text=f'保存位置：{SEMANTICS_DIR}')

    def execute(self, context):
        name = self.name.strip()
        if not name:
            self.report({'ERROR'}, '请输入方案名称')
            return {'CANCELLED'}
        mapping = {}
        for e in context.scene.bufferio_elements:
            key = f'{e.semantic_name} {e.semantic_index}'
            # 值格式：带索引的语义保存为 "TEXCOORD 0" 形式
            if e.index > 0 or e.semantic in INDEXED_SEMANTICS:
                mapping[key] = f'{e.semantic} {e.index}'
            else:
                mapping[key] = e.semantic
        try:
            SEMANTICS_DIR.mkdir(parents=True, exist_ok=True)
            with open(SEMANTICS_DIR / f'{name}.json', 'w', encoding='utf-8') as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.report({'ERROR'}, f'保存失败: {exc}')
            return {'CANCELLED'}
        self.report({'INFO'}, f'已保存 {len(mapping)} 条语义映射：{name}')
        return {'FINISHED'}


class BUFFERIO_OT_load_semantics(bpy.types.Operator):
    """从插件本地加载语义映射并应用到当前元素列表"""
    bl_idname = 'bufferio.load_semantics'
    bl_label = 'Load Semantics'
    bl_options = {'REGISTER', 'UNDO'}

    scheme: EnumProperty(name='方案', items=_semantics_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'scheme')

    def execute(self, context):
        if not self.scheme:
            self.report({'ERROR'}, '没有可用的语义方案')
            return {'CANCELLED'}
        try:
            with open(SEMANTICS_DIR / f'{self.scheme}.json', 'r', encoding='utf-8') as f:
                mapping = json.load(f)
        except Exception as exc:
            self.report({'ERROR'}, f'读取失败: {exc}')
            return {'CANCELLED'}

        valid = {i[0] for i in ELEMENT_SEMANTIC_ITEMS}
        applied = 0
        for e in context.scene.bufferio_elements:
            key = f'{e.semantic_name} {e.semantic_index}'
            value = mapping.get(key)
            if not value:
                continue
            # 值格式 "TEXCOORD 0"：空格后为索引；纯语义名则索引保持 0
            parts = value.split(' ')
            if parts[0] not in valid:
                continue
            e.semantic = parts[0]
            if len(parts) > 1 and parts[1].isdigit():
                e.index = int(parts[1])
            else:
                e.index = 0
            applied += 1
        self.report({'INFO'}, f'已应用 {applied} 条语义映射')
        return {'FINISHED'}


class BUFFERIO_OT_save_mesh_preset(bpy.types.Operator):
    """把当前 Mesh 模式属性配置保存为预设（不含文件路径）"""
    bl_idname = 'bufferio.save_mesh_preset'
    bl_label = '保存预设'
    bl_options = {'REGISTER'}

    name: StringProperty(name='预设名称', default='')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'name')
        layout.label(text=f'保存位置：{MESH_PRESETS_DIR}')

    def execute(self, context):
        name = self.name.strip()
        if not name:
            self.report({'ERROR'}, '请输入预设名称')
            return {'CANCELLED'}
        # 参考 fmt 的 element 结构（SemanticName/SemanticIndex/Format/Offset），不含路径
        preset = []
        for a in context.scene.bufferio_attributes:
            preset.append({
                'semantic': a.semantic,
                'semantic_index': a.semantic_index,
                'format': a.format,
                'stride': a.stride,
                'offset': a.offset,
                'name': a.export_name,
            })
        try:
            MESH_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
            with open(MESH_PRESETS_DIR / f'{name}.json', 'w', encoding='utf-8') as f:
                json.dump(preset, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.report({'ERROR'}, f'保存失败: {exc}')
            return {'CANCELLED'}
        self.report({'INFO'}, f'已保存 {len(preset)} 项预设：{name}')
        return {'FINISHED'}


class BUFFERIO_OT_load_mesh_preset(bpy.types.Operator):
    """从插件本地加载 Mesh 预设并重建属性列表"""
    bl_idname = 'bufferio.load_mesh_preset'
    bl_label = '加载预设'
    bl_options = {'REGISTER', 'UNDO'}

    scheme: EnumProperty(name='预设', items=_mesh_preset_items)

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
            with open(MESH_PRESETS_DIR / f'{self.scheme}.json', 'r', encoding='utf-8') as f:
                preset = json.load(f)
        except Exception as exc:
            self.report({'ERROR'}, f'读取失败: {exc}')
            return {'CANCELLED'}

        valid_sem = {i[0] for i in ATTRIBUTE_SEMANTIC_ITEMS}
        valid_fmt = {i[0] for i in dxgi.format_enum_items()}
        attrs = context.scene.bufferio_attributes
        attrs.clear()
        for d in preset:
            if d.get('semantic') not in valid_sem:
                continue
            a = attrs.add()
            _assign_id(attrs, a)
            a.enabled = True
            a.semantic = d['semantic']
            a.semantic_index = d.get('semantic_index', 0)
            if d.get('format') in valid_fmt:
                a.format = d['format']
            a.stride = d.get('stride', 0)
            a.offset = d.get('offset', 0)
            a.export_name = d.get('name', d.get('export_name', ''))
        context.scene.bufferio_attributes_index = 0
        self.report({'INFO'}, f'已加载 {len(attrs)} 项预设：{self.scheme}')
        return {'FINISHED'}


class BUFFERIO_OT_fa_paths(bpy.types.Operator):
    """选择 FrameAnalysis 资源文件，按前缀自动搜索同前缀文件并填入列表项路径"""
    bl_idname = 'bufferio.fa_paths'
    bl_label = 'FrameAnalysis 导入路径'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.buf;*.txt', options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = Path(bpy.path.abspath(self.filepath))
        if not path.is_file():
            self.report({'ERROR'}, '文件不存在')
            return {'CANCELLED'}
        name = path.name
        # 提取前缀（第一个 - 之前），如 `000055-ib=...` -> `000055`
        dash = name.find('-')
        if dash <= 0:
            self.report({'ERROR'}, '无法从文件名识别 FrameAnalysis 前缀')
            return {'CANCELLED'}
        prefix = name[:dash]
        # 扫描同目录同前缀文件，tag -> 文件列表（如 vb0 / vs-cb4 / ib）
        found = {}
        for f in path.parent.glob(f'{prefix}-*'):
            if not f.is_file():
                continue
            rest = f.name[len(prefix) + 1:]
            tag = rest.split('=', 1)[0]
            if tag:
                found.setdefault(tag, []).append(f)
        # 按列表项名称（tag）填入对应文件：
        # INDEX 项填 buf 数据 + ib txt（含 first/vertex），其他项优先 .buf
        applied = 0
        for a in context.scene.bufferio_attributes:
            tag = a.export_name.strip()
            if not tag:
                continue
            candidates = found.get(tag)
            if not candidates:
                continue
            if a.semantic == 'INDEX':
                # 优先 .buf 数据文件，同时若有同前缀 ib txt 则一并填入（含 first/vertex）
                buf = next((p for p in candidates if p.suffix.lower() == '.buf'), candidates[0])
                txt = next((p for p in candidates if p.suffix.lower() == '.txt'), None)
                a.filepath = str(buf)
                if txt is not None:
                    a.ib_txt = str(txt)
                    try:
                        fmt = fmt_parser.parse_fmt_file(txt)
                        a.first_vertex = fmt.first_index
                        a.vertex_count = fmt.index_count
                    except Exception:
                        pass
            else:
                candidates = sorted(candidates,
                                    key=lambda p: (p.suffix.lower() != '.buf', p.name))
                a.filepath = str(candidates[0])
            applied += 1
        self.report({'INFO'},
                    f'前缀 {prefix}：找到 {len(found)} 类资源，已填入 {applied} 项路径')
        return {'FINISHED'}


class BUFFERIO_OT_load_fmt(bpy.types.Operator):
    bl_idname = 'bufferio.load_fmt'
    bl_label = '加载 FMT'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.fmt;*.txt', options={'HIDDEN'})

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
                self._add_element(scene, element, fmt.stride, vb_path)
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
            for element in fmt.elements:
                if not element.is_per_vertex:
                    continue
                vb_path = resources.vb_files.get(element.input_slot)
                if vb_path is None:
                    self.report({'ERROR'},
                                f'找不到 InputSlot {element.input_slot} 对应的 vb 文件')
                    return {'CANCELLED'}
                self._add_element(scene, element,
                                  slot_strides[element.input_slot], str(vb_path))
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
        self.report({'INFO'}, info)
        return {'FINISHED'}

    @staticmethod
    def _add_element(scene, element, stride, source_file):
        item = scene.bufferio_elements.add()
        _assign_id(scene.bufferio_elements, item)
        item.enabled = element.is_per_vertex
        # 语义名/索引由列表行内与属性面板显示，label 只保留缓冲槽位/偏移
        item.label = f'vb{element.input_slot} +{element.byte_offset}'
        item.semantic_name = element.semantic_name
        item.semantic = SEMANTIC_GUESS.get(element.semantic_name, 'SKIP')
        item.semantic_index = element.semantic_index
        # 目标索引默认与语义索引一致，可在属性面板中修改
        item.index = element.semantic_index
        if element.format in dxgi.SUPPORTED_FORMATS:
            item.format = element.format
        item.input_slot = element.input_slot
        item.offset = element.byte_offset
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
        item.input_slot = -1
        item.offset = byte_offset
        item.stride = 0  # 索引为紧凑数据
        item.filepath = filepath
        item.label = f'IB ({Path(filepath).name})'
        # 从 ib txt 头部填充 first vertex / vertex count，并保留 txt 作为兜底
        if ib_txt and Path(ib_txt).is_file():
            item.ib_txt = ib_txt
            try:
                fmt = fmt_parser.parse_fmt_file(Path(ib_txt))
                item.first_vertex = fmt.first_index
                item.vertex_count = fmt.index_count
            except Exception:
                pass
        return item


class BUFFERIO_OT_import_mesh(bpy.types.Operator):
    bl_idname = 'bufferio.import_mesh'
    bl_label = '导入（Mesh 模式）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        attrs = scene.bufferio_attributes
        if len(attrs) == 0:
            self.report({'ERROR'}, '请先添加属性条目')
            return {'CANCELLED'}

        result = validate_entries(attrs)
        if result['missing']:
            self.report({'WARNING'}, f'缺少必需语义：{", ".join(result["missing"])}')
        try:
            faces, arrays = collect_vertex_arrays(attrs)
            # 网格名取 INDEX 条目文件名；骨架名取 BONEMATRIX 条目文件名（骨骼矩阵文件）
            index_path = next(
                (a.filepath or a.ib_txt for a in attrs
                 if a.enabled and a.semantic == 'INDEX' and (a.filepath or a.ib_txt)), None)
            mesh_name = Path(index_path).name if index_path else 'BufferIO_Mesh'
            bone_path = next(
                (a.filepath for a in attrs
                 if a.enabled and a.semantic == 'BONEMATRIX' and a.filepath), None)
            obj = build_and_link(context, mesh_name, faces, arrays,
                                 scene.bufferio_flip_winding,
                                 scene.bufferio_flip_texcoord_v,
                                 scale=scene.bufferio_global_scale,
                                 mirror_x=scene.bufferio_mirror_x,
                                 axis_forward=scene.bufferio_axis_forward,
                                 axis_up=scene.bufferio_axis_up,
                                 armature_name=Path(bone_path).name if bone_path else None)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'},
                    f'导入完成：{len(obj.data.vertices)} 顶点，{len(obj.data.polygons)} 面')
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
    BUFFERIO_OT_attribute_add,
    BUFFERIO_OT_attribute_remove,
    BUFFERIO_OT_attribute_move,
    BUFFERIO_OT_element_add,
    BUFFERIO_OT_element_remove,
    BUFFERIO_OT_element_move,
    BUFFERIO_OT_validate_all,
    BUFFERIO_OT_save_mesh_preset,
    BUFFERIO_OT_load_mesh_preset,
    BUFFERIO_OT_fa_paths,
    BUFFERIO_OT_save_semantics,
    BUFFERIO_OT_load_semantics,
    BUFFERIO_OT_load_fmt,
    BUFFERIO_OT_import_mesh,
    BUFFERIO_OT_import_fmt,
)
