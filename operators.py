"""BufferIO 操作符：从 FrameAnalysis 文件夹批量生成节点。

选择一个 FrameAnalysis dump 文件夹后按 drawcall 分组扫描：每组由
`<draw id>-ib=<hash>-*.txt` 定位，ib / vb / 骨骼矩阵均从组内文件寻找；
ib hash + first/count + 全部 vb hash 相同的组视为重复，跳过导入。
导入时按解析结果创建 Vertex Buffer / Index Buffer / Mesh Assemble / Import
节点（每组一个节点框）。组按 ib txt 的 first index 升序排列，Import 节点的
Object Name 依次为 Component 0、Component 1……
"""

import re
from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       IntProperty, StringProperty)
from bpy.types import Operator, PropertyGroup

from . import fmt_parser
from .nodes.element_semantic import (BUFFER_SEMANTIC_ITEMS,
                                     EXCLUDED_SEMANTICS, semantic_title)
from .properties import ElementList, _auto_export_name, parse_fmt_elements

# 节点图间距
NODE_GAP_X = 320.0
NODE_GAP_Y = 170.0
# 相邻 drawcall 节点框的水平间距
GROUP_SPACING = 1600.0

# ib txt 文件名：<draw id>-ib=<hash>-...（hash 截到下一个 '-' 或文件名结尾）
IB_TXT_RE = re.compile(r'^(\d+)-ib=([0-9a-fA-F]+)')

# vb 文件名：<draw id>-vb<N>=<hash>-...（骨骼矩阵 vs-cb* 不匹配此模式）
VB_FILE_RE = re.compile(r'^(\d+)-vb\d+=([0-9a-fA-F]+)')

# 游戏列表：当前 FrameAnalysis 布局规则仅有 wuwa 一项
GAME_ITEMS = (
    ('WUWA', 'WuWa', 'Wuthering Waves FrameAnalysis naming rules'),
)


class BUFFERIO_AttributeItem(PropertyGroup):
    """语义映射条目：(Semantic Name, Semantic Index) -> (Semantic, Target Index)"""
    semantic_name: StringProperty(
        name='Semantic Name',
        description='Original semantic name in the fmt (e.g. ATTRIBUTE, TEXCOORD)',
        default='ATTRIBUTE')
    semantic_index: IntProperty(
        name='Semantic Index', default=0, min=0,
        description='Index of the original semantic (e.g. 13 = ATTRIBUTE 13)')
    semantic: EnumProperty(
        name='Target Semantic', items=BUFFER_SEMANTIC_ITEMS, default='POSITION',
        description='Target semantic used by the Vertex Buffer node')
    target_index: IntProperty(
        name='Target Index', default=0, min=0,
        description='Written into the node Semantic Index; also decides the '
                    'join order of BLENDINDICES/WEIGHTS')


def apply_attribute_mapping(elements, attributes):
    """按映射条目改写元素的目标语义与目标索引，返回被改写的元素数量"""
    mapping = {
        (item.semantic_name.upper(), int(item.semantic_index)):
            (item.semantic, int(item.target_index))
        for item in attributes if item.semantic_name
    }
    changed = 0
    for elem in elements:
        target = mapping.get((elem.semantic_name.upper(), elem.semantic_index))
        if target is None:
            continue
        elem.semantic, elem.index = target
        elem.semantic_index = target[1]
        changed += 1
    return changed


class BUFFERIO_OT_import_fmt_attribute(Operator):
    """Add or remove a semantic mapping entry"""
    bl_idname = 'bufferio.import_fmt_attribute'
    bl_label = 'Adjust Mapping Entries'
    bl_options = {'INTERNAL'}

    index: IntProperty(default=0)
    delta: IntProperty(default=1, min=-1, max=1)

    def execute(self, context):
        # 文件对话框 / 调整面板中由 Blender 把当前操作符设为 active_operator
        op = getattr(context, 'active_operator', None)
        if op is None or op.bl_idname != 'BUFFERIO_OT_node_import_fmt':
            return {'CANCELLED'}
        if self.delta > 0:
            op.attributes.add()
        elif self.index < len(op.attributes):
            op.attributes.remove(self.index)
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


def _layout(node, frame, x, y):
    """把节点挂到节点框下，并按框内相对坐标摆放"""
    node.parent = frame
    node.location = (x, y)


def _insert_mesh_stage(tree, target, node):
    """把 node 插入到 target 的 Mesh 输入之前，保留已存在的上游连线"""
    socket = target.inputs.get('Mesh')
    upstream = None
    if socket is not None and socket.is_linked:
        link = socket.links[0]
        upstream = (link.from_node, link.from_socket)
        tree.links.remove(link)
    if upstream is not None:
        tree.links.new(upstream[1], node.inputs['Mesh'])
    if socket is not None:
        tree.links.new(node.outputs['Mesh'], socket)


def _add_shapekey_nodes(tree, frame, target, directory, prefix, report, x, y):
    """wuwa 形态键：按 draw id 前缀自动发现并创建一个多槽位的形态键装配节点"""
    mapping = wuwa_shapekey_map(Path(directory), prefix, report)
    if not mapping:
        return 0

    # 每组形态键一个槽位：ShapeKey Resource -> SHAPEKEY[i]
    stage = tree.nodes.new('BufferIOShapeKeyApply')
    stage.shape_count = len(mapping)
    stage.rebuild_sockets()
    _insert_mesh_stage(tree, target, stage)
    _layout(stage, frame, x + NODE_GAP_X, y)
    for slot, sem_map in sorted(mapping.items()):
        node = tree.nodes.new('BufferIOShapeKey')
        _layout(node, frame, x, y - NODE_GAP_Y * (2 + slot))
        if 'SHAPEKEY_OFFSET' in sem_map:
            node.set_socket_default('Offsets File', str(sem_map['SHAPEKEY_OFFSET']))
        if 'SHAPEKEY_VERTEXID' in sem_map:
            node.set_socket_default('IDs File', str(sem_map['SHAPEKEY_VERTEXID']))
        if 'SHAPEKEY_VERTEXOFFSET' in sem_map:
            node.set_socket_default('Vectors File', str(sem_map['SHAPEKEY_VERTEXOFFSET']))
        tree.links.new(node.outputs['ShapeKey'],
                       stage.inputs[f'SHAPEKEY[{slot}]'])
    return len(mapping)


def _add_bone_matrix_node(tree, frame, target, directory, prefix, tag, report, x, y):
    """骨骼矩阵：按资源 tag（如 vs-cb6）在同 drawcall 组内查找矩阵文件并接到 Import 的 Matrix 输入"""
    matches = sorted(Path(directory).glob(f'{prefix}-{tag}=*.buf'))
    if not matches:
        report({'WARNING'}, f'Bone matrix not found: {prefix}-{tag}=*.buf')
        return
    node = tree.nodes.new('BufferIOBoneMatrix')
    _layout(node, frame, x, y - NODE_GAP_Y * 6)
    node.set_socket_default('File', str(matches[0]))
    auto = _auto_export_name(str(matches[0]))
    node.name = auto if auto else tag
    tree.links.new(node.outputs['Matrix'], target.inputs['Matrix'])
    report({'INFO'}, f'Bone matrix: {matches[0].name}')


def _active_node_tree(context):
    from .nodes.ui import _active_tree
    return _active_tree(context)


def _scan_drawcalls(folder):
    """扫描文件夹内所有 drawcall 分组

    每个分组：{'ib_txt','ib_hash','first','count','vb_hashes','vb_txts'}
    目录只遍历一次：vb 的 hash 与 txt 头部文件在这里一并收集，
    避免后续每个 draw id 各做一次 glob。
    """
    vb_hashes = {}
    vb_txts = {}
    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        match = VB_FILE_RE.match(entry.name)
        if match is None:
            continue
        draw_id = match.group(1)
        vb_hashes.setdefault(draw_id, set()).add(match.group(2).lower())
        if entry.suffix.lower() == '.txt':
            vb_txts.setdefault(draw_id, []).append(entry)

    groups = {}
    for txt in sorted(folder.glob('*-ib=*.txt')):
        match = IB_TXT_RE.match(txt.name)
        if match is None:
            continue
        draw_id, ib_hash = match.group(1), match.group(2)
        try:
            header = fmt_parser.parse_fmt_file(txt)
        except Exception:
            continue  # 无法解析头部的 ib txt 跳过
        groups[draw_id] = {'ib_txt': txt, 'ib_hash': ib_hash.lower(),
                           'first': header.first_index,
                           'count': header.index_count,
                           'vb_hashes': vb_hashes.get(draw_id, set()),
                           'vb_txts': sorted(vb_txts.get(draw_id, []))}
    return groups


def _find_layout_txt(candidates):
    """在已收集的 vb txt 中找含 IA 布局定义（element[]）的文件"""
    for txt in candidates:
        try:
            if fmt_parser.parse_fmt_file(txt).elements:
                return txt
        except Exception:
            continue
    return None


class BUFFERIO_OT_node_import_fmt(Operator):
    """选择 FrameAnalysis dump 文件夹，按 drawcall 分组批量生成 VB / Index / Assemble / Import 节点"""
    bl_idname = 'bufferio.node_import_fmt'
    bl_label = 'FrameAnalysis Import'
    # 'PRESET'：文件对话框右侧自动绘制原生操作项预设行
    # （WM_MT_operator_presets 下拉 + 添加/移除，见 template_operator_property）
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}

    game: EnumProperty(
        name='Game', items=GAME_ITEMS, default='WUWA',
        description='Layout rules used to interpret the FrameAnalysis folder')
    # 文件夹选择：use_filter_folder 让文件浏览器进入目录模式，结果写入 directory
    directory: StringProperty(
        name='Folder', subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    filepath: StringProperty(
        name='Path', subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    use_filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_glob: StringProperty(default='*', options={'HIDDEN', 'SKIP_SAVE'})
    use_mapping: BoolProperty(
        name='Semantic Mapping',
        default=False,
        description='Map the fmt semantics by the list below instead of '
                    'guessing from the SemanticName',
    )
    attributes: CollectionProperty(
        name='Attributes',
        type=BUFFERIO_AttributeItem,
        description='Mapping from (Semantic Name, Semantic Index) in the fmt '
                    'to the target semantic and index',
    )
    search_shape_keys: BoolProperty(
        name='Search Shape Keys',
        default=False,
        description='Search WuWa shape key CS calls through the vb6 hash and '
                    'add shape key nodes automatically',
    )
    bone_matrix_tag: StringProperty(
        name='Bone Matrix Tag',
        description='Resource tag (e.g. vs-cb6); the bone matrix of the same draw call is searched automatically and a bone matrix node is added',
        default='vs-cb6',
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        """文件对话框右侧面板：全部可调选项（预设行由 Blender 自动绘制）"""
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.prop(self, 'game')
        col.prop(self, 'use_mapping')
        col.prop(self, 'search_shape_keys')
        col.prop(self, 'bone_matrix_tag')

        if not self.use_mapping:
            return
        layout.use_property_split = False
        box = layout.box()
        row = box.row(align=True)
        row.label(text='Source')
        row.label(text='Target')
        for item in self.attributes:
            row = box.row(align=True)
            row.prop(item, 'semantic_name', text='')
            row.prop(item, 'semantic_index', text='')
            row.label(icon='ARROW_LEFTRIGHT')
            row.prop(item, 'semantic', text='')
            row.prop(item, 'target_index', text='')
        row = box.row(align=True)
        op = row.operator('bufferio.import_fmt_attribute',
                          text='Attribute', icon='ADD')
        op.index = len(self.attributes)
        op.delta = 1
        op = row.operator('bufferio.import_fmt_attribute',
                          text='Attribute', icon='REMOVE')
        op.index = max(0, len(self.attributes) - 1)
        op.delta = -1

    def execute(self, context):
        if self.game != 'WUWA':
            self.report({'ERROR'}, f'Unsupported game: {self.game}')
            return {'CANCELLED'}

        tree = _active_node_tree(context)
        if tree is None:
            tree = bpy.data.node_groups.new('BufferIO', 'BufferIONodeTree')
            tree.use_fake_user = True
            scene = getattr(context, 'scene', None)
            if scene is not None:
                scene.bufferio_node_tree = tree

        folder = Path(bpy.path.abspath(self.directory or self.filepath))
        if not folder.is_dir():
            self.report({'ERROR'}, f'Folder not found: {folder}')
            return {'CANCELLED'}

        # 按 drawcall 分组扫描；ib hash + first/count + 全部 vb hash 相同视为重复
        # （vb 只看 hash，骨骼矩阵 vs-cb* 不参与去重）
        groups = _scan_drawcalls(folder)
        if not groups:
            self.report({'ERROR'}, f'No ib txt found in: {folder}')
            return {'CANCELLED'}

        seen = set()
        ordered = []
        for draw_id in sorted(groups, key=int):
            group = groups[draw_id]
            key = (group['ib_hash'], group['first'], group['count'],
                   tuple(sorted(group['vb_hashes'])))
            if key in seen:
                self.report({'WARNING'},
                            f'Skip drawcall {draw_id}: duplicate ib / vb hashes')
                continue
            seen.add(key)
            ordered.append((draw_id, group))

        # 按 ib txt 的 first index 从小到大排序：顺序即 Component 0、Component 1……
        ordered.sort(key=lambda item: (item[1]['first'], int(item[0])))

        cursor = getattr(getattr(context, 'space_data', None),
                         'cursor_location', None)
        base_x = cursor.x if cursor is not None else 0.0
        base_y = cursor.y if cursor is not None else 0.0

        imported = 0
        for index, (draw_id, group) in enumerate(ordered):
            layout_txt = _find_layout_txt(group['vb_txts'])
            if layout_txt is None:
                self.report({'WARNING'},
                            f'Drawcall {draw_id}: no vb txt with IA layout, skipped')
                continue
            elements = ElementList()
            try:
                parse_fmt_elements(elements, layout_txt)
            except Exception as exc:
                self.report({'WARNING'},
                            f'Drawcall {draw_id}: parse failed ({exc}), skipped')
                continue
            if self.use_mapping:
                apply_attribute_mapping(elements, self.attributes)

            offset = base_x + index * GROUP_SPACING
            frame = tree.nodes.new('NodeFrame')
            frame.label = f'{draw_id} ib={group["ib_hash"]}'
            frame.use_custom_color = True
            frame.color = (0.15, 0.17, 0.23)
            frame.location = (offset, base_y)

            self._create_nodes(tree, frame, elements, offset, base_y,
                               folder, draw_id, f'Component {imported}')
            imported += 1

        if imported == 0:
            self.report({'ERROR'}, 'No drawcall imported')
            return {'CANCELLED'}
        self.report({'INFO'}, f'Imported {imported} drawcall group(s)')
        self.report({'INFO'}, 'Click Import All in the sidebar to build the meshes')
        return {'FINISHED'}

    def _create_nodes(self, tree, frame, elements, base_x, base_y, directory,
                      prefix, object_name):
        """按解析结果创建节点并连线（directory + prefix 用于形态键/骨骼矩阵查找）"""
        ib_elem = next((e for e in elements if e.semantic == 'INDEX'), None)
        vb_elems = [e for e in elements
                    if e.semantic != 'INDEX' and getattr(e, 'enabled', True)]

        index_node = None
        if ib_elem is not None:
            index_node = tree.nodes.new('BufferIOIndexBuffer')
            _layout(index_node, frame, NODE_GAP_X * 1.1, 0.0)
            index_node.set_socket_default('File', ib_elem.filepath)
            index_node.set_socket_default('Format', ib_elem.format)
            index_node.set_socket_default(
                'Byte Offset', int(getattr(ib_elem, 'byte_offset', 0)))
            # ib txt 放在最后设置：其 update 回调会解析头部并覆盖格式/偏移
            if getattr(ib_elem, 'ib_txt', ''):
                index_node.ib_txt = ib_elem.ib_txt
            else:
                index_node.set_socket_default(
                    'First Index', int(getattr(ib_elem, 'first_index', 0)))
                index_node.set_socket_default(
                    'Index Count', int(getattr(ib_elem, 'index_count', 0)))

        vb_nodes = []
        skipped = 0
        for i, elem in enumerate(vb_elems):
            node = tree.nodes.new('BufferIOGenericBuffer')
            _layout(node, frame, 0.0, -NODE_GAP_Y * i)
            node.set_socket_default('File', elem.filepath)
            node.set_socket_default('Format', elem.format)
            node.set_socket_default('Stride', int(getattr(elem, 'stride', 0)))
            node.set_socket_default('Byte Offset', int(getattr(elem, 'byte_offset', 0)))
            node.set_socket_default('Element Offset', int(getattr(elem, 'offset', 0)))
            node.set_socket_default('Count', int(getattr(elem, 'count', 0)))

            semantic = getattr(elem, 'semantic', 'SKIP')
            index = int(getattr(elem, 'index', 0))
            if semantic == 'SKIP' or semantic in EXCLUDED_SEMANTICS:
                # 未识别/顶点缓冲不处理的语义：保留为静音节点，便于手动改语义后接线
                skipped += 1
                node.label = f'{elem.semantic_name or semantic} {index}'
                node.mute = True
            else:
                node.semantic = semantic
                node.semantic_index = index
                node.label = semantic_title(semantic, index)
                vb_nodes.append(node)

        assemble = tree.nodes.new('BufferIOMeshAssemble')
        assemble.array_count = max(1, len(vb_nodes))
        assemble.rebuild_sockets()
        _layout(assemble, frame, NODE_GAP_X * 2.5,
                -NODE_GAP_Y * max(0, len(vb_elems) - 1) / 2.0)
        for i, node in enumerate(vb_nodes):
            tree.links.new(node.outputs['Array'],
                           assemble.inputs[f'ELEMENT[{i}]'])
        if index_node is not None:
            tree.links.new(index_node.outputs['Index'],
                           assemble.inputs['Index'])

        mid_y = -NODE_GAP_Y * max(0, len(vb_elems) - 1) / 2.0

        output = tree.nodes.new('BufferIOImport')
        _layout(output, frame, NODE_GAP_X * 3.5, mid_y)
        output.set_socket_default('Object Name', object_name)
        tree.links.new(assemble.outputs['Mesh'], output.inputs['Mesh'])

        if self.search_shape_keys:
            added = _add_shapekey_nodes(tree, frame, output, directory,
                                        prefix, self.report,
                                        NODE_GAP_X * 3.5, mid_y)
            if added:
                self.report({'INFO'},
                            f'WuWa shape keys: {added} slot(s) on ShapeKey Assemble')
        tag = self.bone_matrix_tag.strip()
        if tag:
            _add_bone_matrix_node(tree, frame, output, directory, prefix,
                                  tag, self.report, NODE_GAP_X * 3.5, mid_y)

        if skipped:
            self.report({'WARNING'},
                        f'{skipped} 个未识别语义的元素已生成静音节点，可手动指定语义后连线')
        tree.nodes.active = output


CLASSES = (
    BUFFERIO_AttributeItem,
    BUFFERIO_OT_import_fmt_attribute,
    BUFFERIO_OT_node_import_fmt,
)
