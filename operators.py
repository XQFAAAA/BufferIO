"""BufferIO 操作符：
- 侧面板：元素增删移动、校验、预设、加载 FMT、导入
- 节点编辑器：VB ELEMENT DESC 解析/元素增删、一键装配、一键导入
"""

import json
import re
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from . import buffer_io
from . import dxgi
from .constants import (
    ELEMENT_SEMANTIC_ITEMS,
    SEMANTICS_DIR,
)
from .core import (
    build_and_link,
    collect_vertex_arrays,
    validate_entries,
)
from .properties import (
    _assign_id,
    _auto_export_name,
    parse_fmt_elements,
)

# 装配链节点（一键装配时整体重建；变换/骨骼矩阵已并入 Import 节点，不再单独成节点）
CHAIN_NODES = {'BufferIOMeshAssemble', 'BufferIOOutput', 'BufferIOShapeKey',
               'BufferIOShapeKeyApply', 'BufferIOBoneMatrix',
               'BufferIOGenericBuffer'}
# 节点图水平/垂直间距
NODE_GAP_X = 320.0
NODE_GAP_Y = 170.0


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
        warn('WuWa: no vb6 file found with the same prefix')
        return None
    m = re.search(r'-vb6=([0-9a-f]+)-', vb6_matches[0].name)
    if not m:
        warn('WuWa: cannot extract hash from the vb6 filename')
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
        warn(f'WuWa: no shape key CS call found for hash {vb6_hash}')
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
        warn('WuWa: no shape key CS data file found')
        return None
    if report is not None:
        report({'INFO'}, f'WuWa: vb6 hash {vb6_hash}, shape key draws {sorted(draw_ids)}')
    return result


# --- 侧面板：元素列表 ------------------------------------------------------

class BUFFERIO_OT_element_add(bpy.types.Operator):
    bl_idname = 'bufferio.element_add'
    bl_label = 'Add Element'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        elems = context.scene.bufferio_elements
        item = elems.add()
        _assign_id(elems, item)
        item.enabled = True
        item.name = 'Custom Element'
        item.format = 'R32G32B32_FLOAT'
        context.scene.bufferio_elements_index = len(elems) - 1
        return {'FINISHED'}


class BUFFERIO_OT_element_remove(bpy.types.Operator):
    bl_idname = 'bufferio.element_remove'
    bl_label = 'Remove Element'
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
    bl_label = 'Move Element'
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name='Direction', items=(('UP', 'Up', ''), ('DOWN', 'Down', '')))

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
    bl_label = 'Validate Stride/Offset'
    bl_options = {'REGISTER'}

    def execute(self, context):
        result = validate_entries(context.scene.bufferio_elements)
        self.report({'INFO'},
                    f'Validation finished: {result["red"]} ERROR item(s) (stride mismatch / out of bounds / semantic conflict), '
                    f'{result["yellow"]} QUESTION item(s) (discontinuous offset layout)')
        if result['missing']:
            self.report({'WARNING'}, f'Missing required semantic: {", ".join(result["missing"])}')
        return {'FINISHED'}


class BUFFERIO_OT_save_semantics(bpy.types.Operator):
    """把当前 FMT 模式元素配置保存为预设（不含文件路径）"""
    bl_idname = 'bufferio.save_semantics'
    bl_label = 'Save Semantic Preset'
    bl_options = {'REGISTER'}

    name: StringProperty(name='Preset Name', default='')
    node_name: StringProperty(name='Node', default='')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'name')
        layout.label(text=f'Save location: {SEMANTICS_DIR}')

    def execute(self, context):
        name = self.name.strip()
        if not name:
            self.report({'ERROR'}, 'Please enter a preset name')
            return {'CANCELLED'}
        elems, node = _preset_target(context, self.node_name)
        if elems is None:
            self.report({'ERROR'}, 'VB ELEMENT DESC node not found')
            return {'CANCELLED'}
        preset = []
        for e in elems:
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
            self.report({'ERROR'}, f'Save failed: {exc}')
            return {'CANCELLED'}
        self.report({'INFO'}, f'Saved preset with {len(preset)} elements: {name}')
        return {'FINISHED'}


class BUFFERIO_OT_load_semantics(bpy.types.Operator):
    """从插件本地加载 FMT 元素预设并重建元素列表（不含文件路径）"""
    bl_idname = 'bufferio.load_semantics'
    bl_label = 'Load Semantic Preset'
    bl_options = {'REGISTER', 'UNDO'}

    scheme: EnumProperty(name='Preset', items=lambda self, context: _preset_items())
    node_name: StringProperty(name='Node', default='')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'scheme')

    def execute(self, context):
        if not self.scheme:
            self.report({'ERROR'}, 'No preset available')
            return {'CANCELLED'}
        try:
            with open(SEMANTICS_DIR / f'{self.scheme}.json', 'r', encoding='utf-8') as f:
                preset = json.load(f)
        except Exception as exc:
            self.report({'ERROR'}, f'Load failed: {exc}')
            return {'CANCELLED'}
        if not isinstance(preset, list):
            self.report({'ERROR'}, f'Incompatible preset format: {self.scheme}')
            return {'CANCELLED'}

        valid_sem = {i[0] for i in ELEMENT_SEMANTIC_ITEMS}
        valid_fmt = set(dxgi.SUPPORTED_FORMATS)
        elems, node = _preset_target(context, self.node_name)
        if elems is None:
            self.report({'ERROR'}, 'VB ELEMENT DESC node not found')
            return {'CANCELLED'}
        # 保留现有文件路径，加载预设后按索引恢复（预设本身不含路径）
        old_paths = [(e.filepath, e.ib_txt) for e in elems]
        if node is not None:
            node['syncing'] = True  # 避免应用预设时逐项回写内部节点
        try:
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
            if node is not None:
                node.elements_index = 0
        finally:
            if node is not None:
                del node['syncing']
                from .nodes.element_desc import rebuild_internal
                # 预设直接修改内部节点：按新元素配置重建内部节点组
                rebuild_internal(node)
                node['bufferio_initialized'] = True
        if node is None:
            context.scene.bufferio_elements_index = 0
        self.report({'INFO'}, f'Loaded preset with {len(elems)} elements: {self.scheme}')
        return {'FINISHED'}


def _preset_target(context, node_name):
    """预设操作对象：VB ELEMENT DESC 节点的元素集合，或场景元素集合"""
    if node_name:
        tree, node = _get_desc_node(context, node_name)
        if node is None:
            return None, None
        return node.elements, node
    return context.scene.bufferio_elements, None


def _preset_items():
    items = []
    if SEMANTICS_DIR.is_dir():
        for path in sorted(SEMANTICS_DIR.glob('*.json')):
            items.append((path.stem, path.stem, str(path)))
    if not items:
        items.append(('', '(No saved preset)', ''))
    return items


# --- 侧面板：加载 FMT / 导入 -----------------------------------------------

class BUFFERIO_OT_load_fmt(bpy.types.Operator):
    bl_idname = 'bufferio.load_fmt'
    bl_label = 'Load FMT'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.fmt;*.txt;*.buf', options={'HIDDEN'})
    shapekey_mode: EnumProperty(
        name='Shape Key Search',
        items=[
            ('NONE', 'None', 'Do not search for shape keys'),
            ('WUWA', 'WuWa', 'WuWa (Wuthering Waves): locate shape key CS calls through a vb6 file with the same prefix, and add SHAPEKEY elements automatically'),
        ],
        default='NONE',
    )
    bone_matrix_tag: StringProperty(
        name='Bone Matrix',
        description='Resource tag (e.g. vs-cb4); after loading, the bone matrix of the same draw call is searched and a BONEMATRIX element is added automatically',
        default='',
    )
    fill_paths_by_tag: BoolProperty(
        name='Fill Paths by Tag',
        description='When enabled, the layout is not parsed; element file paths are filled by filename prefix only (no txt header needed, .buf files can be selected directly). Elements must already exist (add them manually or load a semantic preset)',
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
            self.report({'ERROR'}, f'FMT file not found: {fmt_path}')
            return {'CANCELLED'}

        # 按tag填路径：不解析布局，仅按前缀填充已有元素的路径
        if self.fill_paths_by_tag:
            return self._fill_paths_by_tag(context, fmt_path)

        try:
            info, ib = parse_fmt_elements(scene.bufferio_elements, fmt_path)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        scene.bufferio_ib_file = ib['file']
        scene.bufferio_ib_format = ib['format']
        scene.bufferio_ib_offset = ib['offset']
        scene.bufferio_ib_first = ib['first']
        scene.bufferio_ib_count = ib['count']
        scene.bufferio_fmt_info = info

        result = validate_entries(scene.bufferio_elements)
        if result['missing']:
            self.report({'WARNING'}, f'Missing required semantic: {", ".join(result["missing"])}')

        # wuwa 形态键搜索：自动添加并填入 SHAPEKEY 元素
        if self.shapekey_mode == 'WUWA':
            dash = fmt_path.name.find('-')
            if dash <= 0:
                self.report({'WARNING'}, 'WuWa: cannot identify the FrameAnalysis prefix from the FMT filename')
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
                    self.report({'INFO'}, f'WuWa shape keys: added {added} elements')

        # 骨骼矩阵：填写 tag（如 vs-cb4）后自动查找同 draw call 的骨骼矩阵
        tag = self.bone_matrix_tag.strip()
        if tag:
            dash = fmt_path.name.find('-')
            if dash <= 0:
                self.report({'WARNING'}, 'Cannot identify the FrameAnalysis prefix from the FMT filename')
            else:
                prefix = fmt_path.name[:dash]
                matches = sorted(fmt_path.parent.glob(f'{prefix}-{tag}=*.buf'))
                if not matches:
                    self.report({'WARNING'}, f'Bone matrix not found: {prefix}-{tag}=*.buf')
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
                    self.report({'INFO'}, f'Bone matrix: {matches[0].name}')

        self.report({'INFO'}, info)
        return {'FINISHED'}

    def _fill_paths_by_tag(self, context, fmt_path):
        """按资源 tag 自动填充已有元素的文件路径（不解析布局，无需 txt 头部）

        从所选文件名提取前缀，扫描同前缀资源，按 input_slot 填入 vb 槽位、
        按 INDEX 语义填入 ib；并同步解析对应 txt 头部的 byte offset / first / count。
        元素需已存在（手动添加或加载语义预设），不清空、不重建元素列表。
        """
        prefix = fmt_path.name.split('-', 1)[0]
        if '-' not in fmt_path.name or not prefix:
            self.report({'ERROR'}, 'Cannot identify the FrameAnalysis prefix from the filename')
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
                    from . import fmt_parser
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
                    f'Prefix {prefix}: found {len(found)} resource kinds, filled {applied} paths'
                    + (f', WuWa shape keys {extra}' if extra else ''))
        return {'FINISHED'}


class BUFFERIO_OT_import_fmt(bpy.types.Operator):
    bl_idname = 'bufferio.import_fmt'
    bl_label = 'Import (FMT Mode)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        elements = [e for e in scene.bufferio_elements
                    if e.enabled and e.semantic != 'SKIP']
        if not elements:
            self.report({'ERROR'}, 'No enabled elements; load an FMT file first')
            return {'CANCELLED'}

        result = validate_entries(scene.bufferio_elements)
        if result['missing']:
            self.report({'WARNING'}, f'Missing required semantic: {", ".join(result["missing"])}')
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
                    f'Import finished: {len(obj.data.vertices)} vertices, {len(obj.data.polygons)} faces')
        return {'FINISHED'}


# --- 节点编辑器：VB ELEMENT DESC / 一键装配 / 一键导入 ----------------------

def _active_node_tree(context):
    from .nodes.ui import _active_tree
    return _active_tree(context)


def _get_desc_node(context, node_name):
    tree = _active_node_tree(context)
    node = tree.nodes.get(node_name) if tree is not None else None
    if node is None or node.bl_idname != 'BufferIOSourceFile':
        return None, None
    return tree, node


def _insert_mesh_stage(tree, target, node, x, y):
    """把 node 插入到 target 的 Mesh 输入之前，保留已存在的上游连线"""
    socket = target.inputs.get('Mesh')
    upstream = None
    if socket is not None and socket.is_linked:
        link = socket.links[0]
        upstream = (link.from_node, link.from_socket)
        tree.links.remove(link)
    node.location = (x, y)
    if upstream is not None:
        tree.links.new(upstream[1], node.inputs['Mesh'])
    if socket is not None:
        tree.links.new(node.outputs['Mesh'], socket)


def _build_graph(tree, source, report=None):
    """从 VB ELEMENT DESC 节点生成导入链：网格直接接到 Import 节点。

    资源描述节点内部已把元素装配成单个网格，骨骼矩阵 / 形态键由
    Bone Matrix / Shape Key Assemble 等独立节点处理。
    返回 Import 节点（后续处理节点插入到它的 Mesh 输入之前）。
    """
    def warn(msg):
        if report is not None:
            report({'WARNING'}, msg)

    removed = 0
    for node in list(tree.nodes):
        if node.bl_idname in CHAIN_NODES:
            tree.nodes.remove(node)
            removed += 1
    if removed:
        warn(f'Removed {removed} old assemble chain node(s)')

    if source.outputs.get('Mesh') is None:
        # 旧文件迁移：端口协议变更后按内部节点重建单个 Mesh 输出
        from .nodes.element_desc import sync_ports
        sync_ports(source)

    x0, y0 = source.location.x, source.location.y
    output = tree.nodes.new('BufferIOOutput')
    output.location = (x0 + NODE_GAP_X, y0)
    tree.links.new(source.outputs['Mesh'], output.inputs['Mesh'])
    return output


def _add_shapekey_nodes(tree, source, target, fmt_path, report):
    """wuwa 形态键：自动发现并创建形态键节点，逐组插入 Shape Key Apply"""
    dash = fmt_path.name.find('-')
    if dash <= 0:
        report({'WARNING'}, 'WuWa: cannot identify the FrameAnalysis prefix from the FMT filename')
        return 0
    mapping = wuwa_shapekey_map(fmt_path.parent, fmt_path.name[:dash], report)
    if not mapping:
        return 0
    x0, y0 = source.location.x, source.location.y
    for slot, sem_map in sorted(mapping.items()):
        node = tree.nodes.new('BufferIOShapeKey')
        node.location = (x0 + NODE_GAP_X * 2, y0 - NODE_GAP_Y * (2 + slot))
        if 'SHAPEKEY_OFFSET' in sem_map:
            node.offsets_file = str(sem_map['SHAPEKEY_OFFSET'])
        if 'SHAPEKEY_VERTEXID' in sem_map:
            node.ids_file = str(sem_map['SHAPEKEY_VERTEXID'])
        if 'SHAPEKEY_VERTEXOFFSET' in sem_map:
            node.vecs_file = str(sem_map['SHAPEKEY_VERTEXOFFSET'])
        # 每组形态键一个应用节点，按槽位顺序串联在网格链上
        stage = tree.nodes.new('BufferIOShapeKeyApply')
        _insert_mesh_stage(tree, target, stage,
                           x0 + NODE_GAP_X, y0 - NODE_GAP_Y * (2 + slot))
        tree.links.new(node.outputs['ShapeKey'], stage.inputs['ShapeKey'])
    return len(mapping)


def _add_bone_matrix_node(tree, source, target, fmt_path, tag, report):
    """骨骼矩阵：按资源 tag（如 vs-cb4）查找同 draw call 的矩阵文件并接到 Import 的 Matrix 输入"""
    dash = fmt_path.name.find('-')
    if dash <= 0:
        report({'WARNING'}, 'Cannot identify the FrameAnalysis prefix from the FMT filename')
        return
    prefix = fmt_path.name[:dash]
    matches = sorted(fmt_path.parent.glob(f'{prefix}-{tag}=*.buf'))
    if not matches:
        report({'WARNING'}, f'Bone matrix not found: {prefix}-{tag}=*.buf')
        return
    node = tree.nodes.new('BufferIOBoneMatrix')
    node.location = (source.location.x + NODE_GAP_X,
                     source.location.y - NODE_GAP_Y * 5)
    node.filepath = str(matches[0])
    auto = _auto_export_name(str(matches[0]))
    node.name = auto if auto else tag
    tree.links.new(node.outputs['Matrix'], target.inputs['Matrix'])
    report({'INFO'}, f'Bone matrix: {matches[0].name}')


class BUFFERIO_OT_node_source_refresh(Operator):
    """重新解析 VB ELEMENT DESC 节点的资源文件，刷新元素列表与输出端口"""
    bl_idname = 'bufferio.node_source_refresh'
    bl_label = 'Re-parse'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty(name='Node')

    def execute(self, context):
        tree, node = _get_desc_node(context, self.node_name)
        if node is None:
            self.report({'ERROR'}, 'VB ELEMENT DESC node not found')
            return {'CANCELLED'}
        from .nodes.element_desc import parse_node
        parse_node(node)
        if node.get('info', '').startswith('Parse failed'):
            self.report({'ERROR'}, node.get('info'))
            return {'CANCELLED'}
        return {'FINISHED'}


class BUFFERIO_OT_node_element_add(Operator):
    """为 VB ELEMENT DESC 节点手动添加元素"""
    bl_idname = 'bufferio.node_element_add'
    bl_label = 'Add Element'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty(name='Node')

    def execute(self, context):
        tree, node = _get_desc_node(context, self.node_name)
        if node is None:
            self.report({'ERROR'}, 'VB ELEMENT DESC node not found')
            return {'CANCELLED'}
        item = node.elements.add()
        _assign_id(node.elements, item)
        item.enabled = True
        item.name = 'Custom Element'
        item.format = 'R32G32B32_FLOAT'
        node.elements_index = len(node.elements) - 1
        from .nodes.element_desc import rebuild_internal
        rebuild_internal(node)
        node['bufferio_initialized'] = True
        return {'FINISHED'}


class BUFFERIO_OT_node_element_remove(Operator):
    """移除 VB ELEMENT DESC 节点当前选中元素"""
    bl_idname = 'bufferio.node_element_remove'
    bl_label = 'Remove Element'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty(name='Node')

    def execute(self, context):
        tree, node = _get_desc_node(context, self.node_name)
        if node is None:
            self.report({'ERROR'}, 'VB ELEMENT DESC node not found')
            return {'CANCELLED'}
        index = node.elements_index
        if 0 <= index < len(node.elements):
            node.elements.remove(index)
            node.elements_index = min(index, len(node.elements) - 1)
        from .nodes.element_desc import rebuild_internal
        rebuild_internal(node)
        node['bufferio_initialized'] = True
        return {'FINISHED'}


class BUFFERIO_OT_node_build_graph(Operator):
    """从 VB ELEMENT DESC 节点生成烘焙链：网格装配 + Import"""
    bl_idname = 'bufferio.node_build_graph'
    bl_label = 'Assemble Graph'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty(name='Node')

    def execute(self, context):
        tree, node = _get_desc_node(context, self.node_name)
        if node is None:
            self.report({'ERROR'}, 'VB ELEMENT DESC node not found')
            return {'CANCELLED'}
        _build_graph(tree, node, self.report)
        self.report({'INFO'}, 'Import chain created; click the Import node button to import the model')
        return {'FINISHED'}


class BUFFERIO_OT_node_import_fmt(Operator):
    """选择 FMT / FrameAnalysis 文件，生成 VB ELEMENT DESC 节点与装配链"""
    bl_idname = 'bufferio.node_import_fmt'
    bl_label = 'Import from FMT'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.fmt;*.txt;*.buf', options={'HIDDEN'})
    shapekey_mode: EnumProperty(
        name='Shape Key Search',
        items=[
            ('NONE', 'None', 'Do not search for shape keys'),
            ('WUWA', 'WuWa', 'WuWa (Wuthering Waves): locate shape key CS calls through a vb6 file with the same prefix, and add shape key nodes automatically'),
        ],
        default='NONE',
    )
    bone_matrix_tag: StringProperty(
        name='Bone Matrix Tag',
        description='Resource tag (e.g. vs-cb4); the bone matrix of the same draw call is searched automatically and a bone matrix node is added',
        default='',
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        tree = _active_node_tree(context)
        if tree is None:
            tree = bpy.data.node_groups.new('BufferIO', 'BufferIONodeTree')
            tree.use_fake_user = True
            scene = getattr(context, 'scene', None)
            if scene is not None:
                scene.bufferio_node_tree = tree

        fmt_path = Path(bpy.path.abspath(self.filepath))
        if not fmt_path.is_file():
            self.report({'ERROR'}, f'File not found: {fmt_path}')
            return {'CANCELLED'}

        node = tree.nodes.new('BufferIOSourceFile')
        node.location = (0.0, 0.0)
        node.filepath = self.filepath  # update 回调自动解析

        if not node.elements:
            self.report({'ERROR'}, node.get('info') or 'Parse failed: no elements')
            tree.nodes.remove(node)
            return {'CANCELLED'}

        chain = _build_graph(tree, node, self.report)

        if self.shapekey_mode == 'WUWA':
            added = _add_shapekey_nodes(tree, node, chain, fmt_path,
                                        self.report)
            if added:
                self.report({'INFO'}, f'WuWa shape keys: added {added} ShapeKey Assemble node(s)')
        tag = self.bone_matrix_tag.strip()
        if tag:
            _add_bone_matrix_node(tree, node, chain, fmt_path, tag,
                                  self.report)

        self.report({'INFO'}, 'Node graph created; click the Import node button to import the model')
        return {'FINISHED'}


CLASSES = (
    # 侧面板
    BUFFERIO_OT_element_add,
    BUFFERIO_OT_element_remove,
    BUFFERIO_OT_element_move,
    BUFFERIO_OT_validate_all,
    BUFFERIO_OT_save_semantics,
    BUFFERIO_OT_load_semantics,
    BUFFERIO_OT_load_fmt,
    BUFFERIO_OT_import_fmt,
    # 节点编辑器
    BUFFERIO_OT_node_source_refresh,
    BUFFERIO_OT_node_element_add,
    BUFFERIO_OT_node_element_remove,
    BUFFERIO_OT_node_build_graph,
    BUFFERIO_OT_node_import_fmt,
)
