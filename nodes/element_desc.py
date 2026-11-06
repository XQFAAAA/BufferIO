"""VB ELEMENT DESC 节点：可 Tab 进入内部的节点组。

外部只有一个网格输出：内部是一棵独立的 BufferIONodeTree，由
Vertex Buffer / Index Buffer 节点与一个网格装配节点组成，每个元素对应一个
内部节点，装配节点把各元素组装成网格后接到组输出端口。

骨骼矩阵与形态键不再进入装配节点：矩阵直接连到 Import 节点的 Matrix 输入，
形态键由 ShapeKey Assemble 节点在外部处理。

- 选中节点按 Tab（或点「Edit Interior」）进入，内部再按 Tab 返回上层；
- 编辑外部列表会同步写入内部节点；
- 进入内部修改节点后返回，外部列表按内部节点重建；
- 预设（保存/加载）直接作用于内部节点。
"""

from pathlib import Path

import bpy
from bpy.props import CollectionProperty, IntProperty, PointerProperty, StringProperty

from .. import dxgi
from ..properties import BufferIOElement, parse_fmt_elements
from .base import BufferIONode
from .element_semantic import BUFFER_SEMANTIC_ITEMS
from .evaluator import EvaluationContext, active_link
from .tree import BufferIONodeTree

# 外部输出端口 Socket 类型（装配在内部完成，只输出一个网格）
MESH_SOCKET = 'BufferIOSocketMesh'
# 内部网格装配节点
ASSEMBLE_IDNAME = 'BufferIOMeshAssemble'

DESC_IDNAME = 'BufferIOSourceFile'
ELEMENT_IDNAME = 'BufferIOGenericBuffer'
# 内部可包含的元素节点（Vertex Buffer / Index Buffer）
ELEMENT_NODE_IDNAMES = {ELEMENT_IDNAME, 'BufferIOIndexBuffer'}

VALID_ELEMENT_SEMANTICS = {item[0] for item in BUFFER_SEMANTIC_ITEMS}


# --- 内部节点组 -----------------------------------------------------------

def internal_tree(node, create=True):
    """获取（必要时创建）内部节点组，并记录宿主信息供退出时回跳"""
    tree = node.node_tree
    if tree is None and create:
        tree = bpy.data.node_groups.new(f'{node.name} Inner', 'BufferIONodeTree')
        tree.use_fake_user = True
        node.node_tree = tree
    if tree is not None:
        tree['bufferio_owner_tree'] = node.id_data.name
        tree['bufferio_owner_node'] = node.name
    return tree


def _element_nodes(node):
    """内部树中的元素节点，按元素顺序（elem_order）排序"""
    tree = node.node_tree
    if tree is None:
        return []
    items = [n for n in tree.nodes if n.bl_idname in ELEMENT_NODE_IDNAMES]
    items.sort(key=lambda n: (int(n.get('elem_order', 999999)), -n.location.y))
    return items


def _ensure_elem_id(inner):
    """确保内部节点带有唯一 elem_id（与外部元素 id 一一对应）"""
    value = inner.get('elem_id')
    if value:
        return int(value)
    used = {int(n.get('elem_id')) for n in inner.id_data.nodes
            if n.as_pointer() != inner.as_pointer() and n.get('elem_id')}
    value = 1
    while value in used:
        value += 1
    inner['elem_id'] = value
    return value


def _find_inner(node, elem_id):
    if elem_id is None:
        return None
    for inner in _element_nodes(node):
        if _ensure_elem_id(inner) == int(elem_id):
            return inner
    return None


def _valid_format(name, fallback):
    return name if name in dxgi.SUPPORTED_FORMATS else fallback


def _output_socket(inner):
    for socket in inner.outputs:
        if socket.bl_idname != 'NodeSocketVirtual':
            return socket
    return None


def _find_assemble(tree):
    """内部网格装配节点（没有则返回 None）"""
    return next((n for n in tree.nodes
                 if n.bl_idname == ASSEMBLE_IDNAME), None)


def _assemble_node(tree):
    """内部网格装配节点（不存在时创建）"""
    node = _find_assemble(tree)
    if node is None:
        node = tree.nodes.new(ASSEMBLE_IDNAME)
        node.location = (200.0, 0.0)
    return node


# --- 组接口：Group Input / Group Output ----------------------------------

GROUP_INPUT_IDNAME = 'NodeGroupInput'
GROUP_OUTPUT_IDNAME = 'NodeGroupOutput'


def _group_node(tree, idname, location):
    """取内部树的组输入/组输出节点，没有则创建"""
    for n in tree.nodes:
        if n.bl_idname == idname:
            return n
    node = tree.nodes.new(idname)
    node.location = location
    return node


def _iface_output_items(tree):
    """树的接口中所有「输出端口」项"""
    return [item for item in tree.interface.items_tree
            if getattr(item, 'in_out', '') == 'OUTPUT']


def sync_interface(node):
    """把内部装配链同步到内部树的接口。

    内部：元素节点 -> 网格装配 -> 组输出；接口只有一个 Mesh 输出端口，
    外部看到的也就只有一个网格输出。

    元素结构（类型/编号/静音/数组槽位数）未变化时直接返回，
    避免每次改文件名或格式都全量断线重连。
    """
    tree = node.node_tree
    if tree is None:
        return

    enabled = [inner for inner in _element_nodes(node) if not inner.mute]
    array_slots = max(sum(1 for inner in enabled
                          if inner.bl_idname != 'BufferIOIndexBuffer'), 1)
    signature = '|'.join(
        f'{inner.bl_idname}:{_ensure_elem_id(inner)}:{int(bool(inner.mute))}'
        for inner in _element_nodes(node)) + f'#{array_slots}'

    items = _iface_output_items(tree)
    items_ok = ([(item.name, item.socket_type) for item in items]
                == [('Mesh', MESH_SOCKET)])
    if items_ok and node.get('bufferio_sync_sig') == signature:
        return

    _group_node(tree, GROUP_INPUT_IDNAME, (-420.0, 0.0))
    gout = _group_node(tree, GROUP_OUTPUT_IDNAME, (620.0, 0.0))

    if not items_ok:
        for item in items:
            tree.interface.remove(item)
        tree.interface.new_socket('Mesh', in_out='OUTPUT', socket_type=MESH_SOCKET)

    # 元素节点 -> 网格装配（按元素顺序分配索引/数组插槽）
    assemble = _assemble_node(tree)
    if assemble.array_count != array_slots:
        assemble.array_count = array_slots
        assemble.rebuild_sockets()
    for socket in assemble.inputs:
        for link in list(socket.links):
            tree.links.remove(link)
    arr_i = 0
    for inner in enabled:
        source = _output_socket(inner)
        if source is None:
            continue
        if inner.bl_idname == 'BufferIOIndexBuffer':
            target = assemble.inputs.get('Index')
        else:
            target = assemble.inputs.get(f'ELEMENT[{arr_i}]')
            arr_i += 1
        if target is not None:
            tree.links.new(source, target)

    # 网格装配 -> 组输出
    target = gout.inputs.get('Mesh')
    if target is not None:
        for link in list(target.links):
            tree.links.remove(link)
        tree.links.new(assemble.outputs['Mesh'], target)

    node['bufferio_sync_sig'] = signature


# --- 外部 Socket <-> 内部节点 ---------------------------------------------

def sync_sockets(node):
    """外部只有一个 Mesh 输出端口"""
    existing = node.outputs.get('Mesh')
    if (len(node.outputs) == 1 and existing is not None
            and existing.bl_idname == MESH_SOCKET and existing.name == 'Mesh'):
        return
    for socket in list(node.outputs):
        if socket.bl_idname != MESH_SOCKET or socket.name != 'Mesh':
            node.outputs.remove(socket)
    if node.outputs.get('Mesh') is None:
        node.outputs.new(MESH_SOCKET, 'Mesh')
    node['bufferio_socket_ids'] = {}


def sync_ports(node):
    """同步组接口与外部端口（元素增删/属性变更后调用）"""
    sync_interface(node)
    sync_sockets(node)


# --- 元素数据 <-> 内部节点 ---------------------------------------------

def _apply_element_to_node(elem, inner):
    """把外部元素属性写入内部节点"""
    if inner.bl_idname == 'BufferIOIndexBuffer':
        inner.filepath = elem.filepath or ''
        inner.ib_txt = elem.ib_txt or ''
        inner.format = _valid_format(elem.format, 'R16_UINT')
        inner.byte_offset = max(int(elem.byte_offset), 0)
        inner.first_index = max(int(elem.first_index), 0)
        inner.index_count = max(int(elem.index_count), 0)
        inner.count = max(int(elem.count), 0)
    else:
        inner.filepath = elem.filepath or elem.source_file or ''
        inner.format = _valid_format(elem.format, 'R32G32B32_FLOAT')
        inner.stride = max(int(elem.stride), 0)
        inner.byte_offset = max(int(elem.byte_offset), 0)
        inner.elem_offset = max(int(elem.offset), 0)
        inner.count = max(int(elem.count), 0)
        inner.semantic = (elem.semantic
                          if elem.semantic in VALID_ELEMENT_SEMANTICS
                          else 'POSITION')
        inner.semantic_index = max(int(elem.index), 0)


def _apply_node_to_element(elem, inner):
    """把内部节点属性回写到外部元素（显示用投影）"""
    elem.enabled = not inner.mute
    if inner.bl_idname == 'BufferIOIndexBuffer':
        elem.semantic_name = 'INDEX'
        elem.semantic = 'INDEX'
        elem.semantic_index = 0
        elem.index = 0
        elem.input_slot = -1
        elem.stride = 0
        elem.offset = 0
        elem.filepath = inner.filepath
        elem.ib_txt = inner.ib_txt
        elem.format = inner.format
        elem.byte_offset = inner.byte_offset
        elem.first_index = inner.first_index
        elem.index_count = inner.index_count
        elem.count = inner.count
    else:
        elem.semantic = inner.semantic
        elem.semantic_index = inner.semantic_index
        elem.index = inner.semantic_index
        elem.filepath = inner.filepath
        elem.source_file = inner.filepath
        elem.format = inner.format
        elem.stride = inner.stride
        elem.byte_offset = inner.byte_offset
        elem.offset = inner.elem_offset
        elem.count = inner.count


def has_internal_elements(node):
    """内部是否已有元素节点（便于判断旧节点/手工改动的同步方向）"""
    return bool(_element_nodes(node))


def rebuild_internal(node):
    """按外部元素列表重建内部节点组（解析 / 增删元素 / 加载预设后调用）"""
    tree = internal_tree(node)
    if tree is None:
        return
    tree.nodes.clear()
    # 节点全部重建，装配连线必须重建，清掉同步标记
    node['bufferio_sync_sig'] = ''
    for order, elem in enumerate(node.elements):
        if elem.semantic == 'SKIP':
            continue  # SKIP 不生成内部节点（外部列表仍保留该行）
        node_type = ('BufferIOIndexBuffer' if elem.semantic == 'INDEX'
                     else ELEMENT_IDNAME)
        inner = tree.nodes.new(node_type)
        inner.location = (0.0, -180.0 * order)
        if elem.name:
            inner.name = elem.name
        inner['elem_id'] = int(elem.id)
        inner['elem_order'] = order
        inner.mute = not elem.enabled
        _apply_element_to_node(elem, inner)
    sync_ports(node)


def refresh_from_internal(node):
    """从内部节点回写外部元素列表（退出节点组时调用）"""
    if node.node_tree is None:
        return
    node['syncing'] = True
    try:
        elems = node.elements
        internals = _element_nodes(node)
        by_id = {_ensure_elem_id(inner): inner for inner in internals}

        # 删除内部已不存在的元素（SKIP 行无内部节点，保留）
        for i in range(len(elems) - 1, -1, -1):
            elem = elems[i]
            if elem.id not in by_id and elem.semantic != 'SKIP':
                elems.remove(i)

        existing = {int(elem.id): elem for elem in elems}
        for inner in internals:
            elem_id = _ensure_elem_id(inner)
            elem = existing.get(elem_id)
            if elem is None:
                elem = elems.add()
                elem.id = elem_id
                elem.name = ('Index Buffer' if inner.bl_idname == 'BufferIOIndexBuffer'
                             else inner.semantic)
                existing[elem_id] = elem
            _apply_node_to_element(elem, inner)
        node.elements_index = max(0, min(node.elements_index, len(elems) - 1))
    finally:
        del node['syncing']
    sync_ports(node)


def notify_element_changed(node, elem):
    """外部元素属性变更：写入对应内部节点并刷新端口"""
    if not isinstance(node, bpy.types.Node) or node.bl_idname != DESC_IDNAME:
        return
    if node.get('syncing'):
        return
    if node.node_tree is None:
        return
    inner = _find_inner(node, elem.id)
    if inner is None:
        rebuild_internal(node)
        return
    expected = ('BufferIOIndexBuffer' if elem.semantic == 'INDEX'
                else ELEMENT_IDNAME)
    if inner.bl_idname != expected:
        rebuild_internal(node)
        return
    inner.mute = not elem.enabled
    _apply_element_to_node(elem, inner)
    sync_ports(node)


# --- 解析 ---------------------------------------------------------------

def parse_node(node):
    """解析资源文件并重建内部节点组（失败时写入节点信息）"""
    if not node.filepath:
        node.elements.clear()
        rebuild_internal(node)
        node.set_info(['Resource file not set'])
        return
    path = Path(bpy.path.abspath(node.filepath))
    if not path.is_file():
        node.set_info([f'File not found: {path}'])
        return
    node['syncing'] = True
    try:
        info, _ib = parse_fmt_elements(node.elements, path)
    except Exception as exc:
        node.set_info([f'Parse failed: {exc}'])
        return
    finally:
        del node['syncing']
    rebuild_internal(node)
    node.set_info([info])


def _update_filepath(node, context):
    if node.get('cloning'):
        return  # 节点克隆期间不重新解析（由内部节点树回填外部列表）
    try:
        parse_node(node)
    except Exception as exc:
        node.set_info([f'Parse failed: {exc}'])


class BUFFERIO_NODE_vb_element_desc(BufferIONode):
    # idname 沿用 BufferIOSourceFile，兼容旧版保存的节点树
    bl_idname = DESC_IDNAME
    bl_label = 'VB ELEMENT DESC'
    bl_description = ('Resource element description node group: built from Vertex Buffer / '
                      'Index Buffer nodes inside and assembled into a single mesh output')
    bl_icon = 'FILE_FOLDER'
    CATEGORY_COLOR = (0.13, 0.24, 0.16)

    filepath: StringProperty(name='File', subtype='FILE_PATH', default='',
                             update=_update_filepath,
                             description='.fmt file or 3dmigoto FrameAnalysis vb txt file path')
    elements: CollectionProperty(type=BufferIOElement)
    elements_index: IntProperty(default=0)
    # 内部节点组（内部由 Vertex Buffer / Index Buffer / Mesh Assemble 组成）
    node_tree: PointerProperty(type=BufferIONodeTree, name='Inner Node Group')

    def init(self, context):
        super().init(context)
        internal_tree(self)
        sync_ports(self)  # 空组也建好 组输入/组输出/装配节点与 Mesh 输出
        self['bufferio_initialized'] = True
        self['bufferio_socket_version'] = 2

    def evaluate(self, ctx):
        tree = self.node_tree
        if tree is None:
            raise ValueError('Inner node group does not exist')
        socket = self.outputs.get('Mesh')
        if socket is None:
            sync_ports(self)  # 旧文件迁移：每个元素一个端口 -> 单个 Mesh
            socket = self.outputs.get('Mesh')
        if socket is None or not socket.is_linked:
            return {}  # 输出未连接时不读取内部数据
        inner_ctx = EvaluationContext(ctx.context, tree,
                                      group_stack=ctx.group_stack + (tree.as_pointer(),))
        gout = next((n for n in tree.nodes
                     if n.bl_idname == GROUP_OUTPUT_IDNAME), None)
        value = None
        # 优先按节点组语义求值：组输出端口 -> 上游连线
        if gout is not None:
            link = active_link(gout.inputs.get('Mesh'))
            if link is not None:
                value = inner_ctx.evaluate_node(link.from_node).get(
                    link.from_socket.name)
        if value is None:
            # 兜底：直接求值内部装配节点
            assemble = _find_assemble(tree)
            if assemble is not None:
                value = inner_ctx.evaluate_node(assemble).get('Mesh')
        if inner_ctx.errors:
            name, message = inner_ctx.errors[0]
            raise ValueError(f'{name}: {message}')
        if value is None:
            raise ValueError('No mesh data from the inner node group')

        vertices = len(next(iter(value.arrays.values()))) if value.arrays else 0
        lines = [
            f'Vertices {vertices}  Triangles '
            f'{len(value.faces) if value.faces is not None else 0}',
        ]
        if value.bone_matrices is not None:
            lines.append(f'Bone Matrices x{len(value.bone_matrices)}')
        if value.shape_keys:
            lines.append(f'Shape Keys x{len(value.shape_keys)}')
        self.set_info(lines)
        return {'Mesh': value}

    def draw_buttons(self, context, layout):
        # 旧版保存的节点没有内部组 / 端口协议已变更：按元素补建
        if (not self.get('bufferio_initialized')
                or self.get('bufferio_socket_version') != 2):
            rebuild_internal(self)
            self['bufferio_initialized'] = True
            self['bufferio_socket_version'] = 2

        layout.prop(self, 'filepath', text='')
        layout.operator('bufferio.node_source_refresh', text='Re-parse',
                        icon='FILE_REFRESH')

        # 预设与进入内部（预设实质是对内部节点操作）
        row = layout.row(align=True)
        op = row.operator('bufferio.save_semantics', text='Save Preset',
                          icon='EXPORT')
        op.node_name = self.name
        op = row.operator('bufferio.load_semantics', text='Load Preset',
                          icon='IMPORT')
        op.node_name = self.name
        op = row.operator('bufferio.node_group_enter', text='Edit Interior',
                          icon='NODETREE')
        op.node_name = self.name

        # 元素列表（与侧面板同一 UIList）：启用状态 / 校验图标 / 目标语义 / 格式
        row = layout.row()
        row.template_list('BUFFERIO_UL_elements', '', self, 'elements',
                          self, 'elements_index', rows=6)
        col = row.column(align=True)
        col.operator('bufferio.node_element_add', icon='ADD', text='')
        col.operator('bufferio.node_element_remove', icon='REMOVE', text='')

        # 选中元素的完整属性（与侧面板元素属性一致）
        index = self.elements_index
        if 0 <= index < len(self.elements):
            item = self.elements[index]
            box = layout.box()
            row = box.row(align=True)
            row.prop(item, 'semantic_name', text='')
            row.prop(item, 'semantic_index', text='')
            row.prop(item, 'semantic', text='')
            row.prop(item, 'index', text='')
            box.prop(item, 'filepath')
            if item.semantic == 'INDEX':
                box.prop(item, 'ib_txt')
                box.prop(item, 'first_index')
                box.prop(item, 'index_count')
            box.prop(item, 'format')
            recommended = [name for name in dxgi.SEMANTIC_FORMATS.get(item.semantic, ())
                           if name in dxgi.SUPPORTED_FORMATS]
            if recommended:
                box.label(text='Recommended Format: ' + ' / '.join(recommended))
            box.prop(item, 'stride')
            box.prop(item, 'offset')
            box.prop(item, 'count')
            box.prop(item, 'byte_offset')

        op = layout.operator('bufferio.node_build_graph', text='Auto Assemble',
                             icon='MESH_DATA')
        op.node_name = self.name

        self.draw_info(layout)


__all__ = (
    'BUFFERIO_NODE_vb_element_desc',
    'sync_sockets',
    'parse_node',
    'rebuild_internal',
    'refresh_from_internal',
    'notify_element_changed',
    'internal_tree',
)
