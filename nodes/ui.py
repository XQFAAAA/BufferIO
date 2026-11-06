"""BufferIO 节点编辑器操作符、侧边栏面板与 Shift+A 添加菜单。"""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel

from .evaluator import EvaluationContext
from .sockets import SOCKET_COLORS

# 节点类型 -> (标签, 图标)，顺序即 Shift+A 菜单中的顺序
NODE_ADD_ITEMS = (
    ('BufferIOSourceFile', 'VB ELEMENT DESC', 'FILE_FOLDER',
     'Node group: built from Vertex Buffer / Index Buffer nodes; outputs a single mesh'),
    ('BufferIOGroup', 'Node Group', 'NODETREE',
     'Empty node group: Tab in to build it, ports come from Group Interface'),
    ('BufferIOIndexBuffer', 'Index Buffer', 'SNAP_VERTEX',
     'Read an index buffer (file or ib txt) and output an index socket'),
    ('BufferIOGenericBuffer', 'Vertex Buffer', 'TEXT',
     'Read an arbitrary vertex buffer and tag a semantic (inner element node of a node group)'),
    ('BufferIOBoneMatrix', 'Bone Matrix', 'BONE_DATA', 'Read bone skinning matrices'),
    ('BufferIOShapeKey', 'ShapeKey Resource', 'SHAPEKEY_DATA',
     'Read a set of segmented shape key data'),
    ('BufferIOShapeKeyApply', 'ShapeKey Assemble', 'SHAPEKEY_DATA',
     'Append a shape key group to a mesh (mesh + shape key -> mesh)'),
    ('BufferIOMeshAssemble', 'Mesh Assemble', 'MESH_DATA', 'Assemble indices and vertex attributes'),
    ('BufferIOOutput', 'Import', 'OBJECT_DATA',
     'Import mesh and/or bone matrices (only matrices = armature only)'),
    ('BufferIOValueFormat', 'Format', 'PROPERTIES', 'Output a DXGI format value'),
    ('BufferIOValueString', 'String', 'FONT_DATA', 'Output a string value'),
    ('BufferIOValueFloat', 'Float', 'DRIVER', 'Output a float value'),
    ('BufferIOValueInt', 'Int', 'LINENUMBERS_ON', 'Output an int value'),
    ('BufferIOValueBool', 'Bool', 'CHECKBOX_HLT', 'Output a bool value'),
)

# 可 Tab 进入内部的节点（资源描述节点组 + 通用节点组）
GROUP_NODE_IDNAMES = {'BufferIOSourceFile', 'BufferIOGroup'}


NODE_ADD_ENUM = tuple((idname, label, description)
                      for idname, label, _, description in NODE_ADD_ITEMS)

# 节点组接口可选的端口类型（与自定义 Socket 一一对应）
SOCKET_TYPE_ITEMS = tuple(
    (name, name.replace('BufferIOSocket', '') or 'Any', '')
    for name in SOCKET_COLORS
)


def _refresh_owner_sockets(tree):
    """节点组接口变更后，重建所有引用该内部树的组节点外部端口

    同一棵内部树可被多个组节点实例共享，全部都要刷新，
    不能只刷新 idprop 里记录的那一个宿主节点。
    """
    from .group import GROUP_IDNAME

    for owner_tree in bpy.data.node_groups:
        for node in owner_tree.nodes:
            if (node.bl_idname == GROUP_IDNAME
                    and node.node_tree is not None
                    and node.node_tree.as_pointer() == tree.as_pointer()):
                node.sync_sockets()


def _interface_tree(context, tree_name):
    """接口操作的目标树：显式 tree_name 优先，否则取当前编辑的树"""
    if tree_name:
        tree = bpy.data.node_groups.get(tree_name)
        if tree is not None and tree.bl_idname == 'BufferIONodeTree':
            return tree
    return _active_tree(context)


def _active_tree(context):
    """优先使用当前节点编辑器中显示的 BufferIO 树"""
    space = getattr(context, 'space_data', None)
    tree = getattr(space, 'edit_tree', None) if space is not None else None
    if tree is not None and tree.bl_idname == 'BufferIONodeTree':
        return tree
    scene = getattr(context, 'scene', None)
    if scene is not None:
        return scene.bufferio_node_tree
    return None


def _draw_add_menu(self, context):
    """Shift+A 菜单中注入 BufferIO 节点（仅在 BufferIO 节点树中显示）"""
    space = getattr(context, 'space_data', None)
    tree = getattr(space, 'edit_tree', None) if space is not None else None
    if tree is None or tree.bl_idname != 'BufferIONodeTree':
        return
    layout = self.layout
    layout.separator()
    layout.label(text='BufferIO', icon='NODETREE')
    column = layout.column()
    for idname, label, icon, _description in NODE_ADD_ITEMS:
        op = column.operator('bufferio.node_add', text=label, icon=icon)
        op.node_type = idname


class BUFFERIO_OT_node_new_tree(Operator):
    bl_idname = 'bufferio.node_new_tree'
    bl_label = 'New Node Tree'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        tree = bpy.data.node_groups.new('BufferIO', 'BufferIONodeTree')
        tree.use_fake_user = True
        scene = getattr(context, 'scene', None)
        if scene is not None:
            scene.bufferio_node_tree = tree
        space = getattr(context, 'space_data', None)
        if space is not None and space.type == 'NODE_EDITOR':
            space.node_tree = tree
        return {'FINISHED'}


class BUFFERIO_OT_node_open_tree(Operator):
    """在当前节点编辑器中打开场景关联的 BufferIO 节点树"""
    bl_idname = 'bufferio.node_open_tree'
    bl_label = 'Open Scene Node Tree'
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, 'space_data', None)
        return (space is not None and space.type == 'NODE_EDITOR'
                and context.scene.bufferio_node_tree is not None)

    def execute(self, context):
        tree = context.scene.bufferio_node_tree
        if tree is not None:
            context.space_data.node_tree = tree
        return {'FINISHED'}


def _selected_group_node(tree):
    """当前选中的可进入节点组节点（没有选中时取活动节点）"""
    node = next((n for n in tree.nodes
                 if n.select and n.bl_idname in GROUP_NODE_IDNAMES), None)
    if node is None:
        node = getattr(tree, 'nodes', None).active if tree is not None else None
        if node is not None and node.bl_idname not in GROUP_NODE_IDNAMES:
            node = None
    return node


def _open_group(context, node):
    """进入节点组内部（Tab 与按钮共用）"""
    from .element_desc import (has_internal_elements, internal_tree,
                               rebuild_internal, refresh_from_internal)

    if node.bl_idname == 'BufferIOSourceFile':
        # 旧版节点或内部为空而外部有元素：按外部元素补建；否则按内部节点回写
        if (not node.get('bufferio_initialized')
                or (len(node.elements) and not has_internal_elements(node))):
            rebuild_internal(node)
            node['bufferio_initialized'] = True
        else:
            refresh_from_internal(node)
        if node.node_tree is None:
            return False
        internal_tree(node)  # 刷新宿主记录，保证 Tab 能返回这一层
    else:
        from .group import ensure_inner
        tree = ensure_inner(node)  # 空组节点在这里补建内部树与组输入/输出节点
        node.sync_sockets()
        tree['bufferio_owner_tree'] = node.id_data.name
        tree['bufferio_owner_node'] = node.name

    context.space_data.node_tree = node.node_tree
    return True


def _owner_node(tree):
    """内部树记录的宿主节点（用于 Tab 返回与判断能否继续编组）"""
    owner_name = str(tree.get('bufferio_owner_tree') or '')
    node_name = str(tree.get('bufferio_owner_node') or '')
    owner_tree = bpy.data.node_groups.get(owner_name)
    if owner_tree is None:
        return None
    return owner_tree.nodes.get(node_name)


def _close_group(context):
    """从内部节点组返回上层树，并同步外层节点"""
    space = context.space_data
    tree = space.edit_tree
    node = _owner_node(tree)
    owner_tree = node.id_data if node is not None else None

    if node is not None and node.bl_idname == 'BufferIOSourceFile':
        from .element_desc import refresh_from_internal
        refresh_from_internal(node)
    elif node is not None and node.bl_idname == 'BufferIOGroup':
        node.sync_sockets()

    if owner_tree is not None:
        context.scene.bufferio_node_tree = owner_tree
        space.node_tree = owner_tree
        return True
    scene_tree = getattr(context.scene, 'bufferio_node_tree', None)
    if scene_tree is None:
        return False
    space.node_tree = scene_tree
    return True


class BUFFERIO_OT_node_group_enter(Operator):
    """进入节点组内部（Tab 与节点上的「编辑内部」按钮共用）"""
    bl_idname = 'bufferio.node_group_enter'
    bl_label = 'Edit Inner Node Group'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()

    @classmethod
    def poll(cls, context):
        space = getattr(context, 'space_data', None)
        tree = getattr(space, 'edit_tree', None) if space is not None else None
        return (space is not None and space.type == 'NODE_EDITOR'
                and tree is not None and tree.bl_idname == 'BufferIONodeTree')

    def execute(self, context):
        tree = _active_tree(context)
        node = tree.nodes.get(self.node_name) if tree is not None else None
        if node is None or node.bl_idname not in GROUP_NODE_IDNAMES:
            self.report({'ERROR'}, 'No node group can be entered')
            return {'CANCELLED'}
        if not _open_group(context, node):
            self.report({'ERROR'}, 'Failed to create the inner node group')
            return {'CANCELLED'}
        return {'FINISHED'}


class BUFFERIO_OT_node_group_exit(Operator):
    """退出内部节点组，返回宿主节点树并同步外部元素列表"""
    bl_idname = 'bufferio.node_group_exit'
    bl_label = 'Exit to Parent'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, 'space_data', None)
        tree = getattr(space, 'edit_tree', None) if space is not None else None
        return (space is not None and space.type == 'NODE_EDITOR'
                and tree is not None and bool(tree.get('bufferio_owner_node')))

    def execute(self, context):
        if not _close_group(context):
            self.report({'ERROR'}, 'Parent node tree not found')
            return {'CANCELLED'}
        return {'FINISHED'}


class BUFFERIO_OT_node_group_toggle(Operator):
    """Tab 键：进入选中的节点组，或在内部按 Tab 返回上层"""
    bl_idname = 'bufferio.node_group_toggle'
    bl_label = 'Enter / Exit Node Group'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, 'space_data', None)
        if space is None or space.type != 'NODE_EDITOR':
            return False
        tree = getattr(space, 'edit_tree', None)
        if tree is None or tree.bl_idname != 'BufferIONodeTree':
            return False
        if tree.get('bufferio_owner_node'):
            return True
        return _selected_group_node(tree) is not None

    def execute(self, context):
        tree = context.space_data.edit_tree
        if tree.get('bufferio_owner_node'):
            return {'FINISHED'} if _close_group(context) else {'CANCELLED'}
        node = _selected_group_node(tree)
        if node is None:
            return {'CANCELLED'}
        return {'FINISHED'} if _open_group(context, node) else {'CANCELLED'}


class BUFFERIO_OT_node_group_make(Operator):
    """把框选的节点合并为一个可 Tab 进入的节点组（Ctrl+G）"""
    bl_idname = 'bufferio.node_group_make'
    bl_label = 'Make Node Group'
    bl_description = 'Merge the selected nodes into a node group (Ctrl+G)'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, 'space_data', None)
        tree = getattr(space, 'edit_tree', None) if space is not None else None
        if space is None or space.type != 'NODE_EDITOR':
            return False
        if tree is None or tree.bl_idname != 'BufferIONodeTree':
            return False
        if tree.get('bufferio_owner_node'):
            # 通用节点组内部可以继续编组；资源描述节点组内部不允许（会打乱元素端口）
            owner = _owner_node(tree)
            return owner is not None and owner.bl_idname == 'BufferIOGroup'
        return True

    def execute(self, context):
        tree = context.space_data.edit_tree
        from .group import make_group
        group = make_group(tree)
        if group is None:
            self.report({'WARNING'}, 'Select the nodes to group first')
            return {'CANCELLED'}
        for node in tree.nodes:
            node.select = False
        group.select = True
        tree.nodes.active = group
        return {'FINISHED'}


class BUFFERIO_OT_node_group_ungroup(Operator):
    """把节点组展开回外层树：内部节点/连线与接口连线一并还原"""
    bl_idname = 'bufferio.node_group_ungroup'
    bl_label = 'Ungroup'
    bl_description = 'Dissolve this node group and restore its nodes and links'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()

    def execute(self, context):
        from .group import ungroup

        tree = _active_tree(context)
        if tree is None:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name) if self.node_name else None
        if node is None:
            # 快捷键调用（Ctrl+Alt+G）：取选中的组节点
            node = next((n for n in tree.nodes
                         if n.select and n.bl_idname == 'BufferIOGroup'), None)
        if node is None:
            self.report({'ERROR'}, 'Node not found')
            return {'CANCELLED'}
        if not ungroup(tree, node):
            self.report({'ERROR'}, 'This node is not a node group')
            return {'CANCELLED'}
        return {'FINISHED'}


class BUFFERIO_OT_node_group_sync(Operator):
    """按内部树接口刷新组节点端口（保留已有连线）

    用于在组外重命名/增删接口后手动同步，避免必须 Tab 进出一次。
    """
    bl_idname = 'bufferio.node_group_sync'
    bl_label = 'Sync Group Ports'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()

    def execute(self, context):
        from .group import GROUP_IDNAME

        tree = _active_tree(context)
        node = tree.nodes.get(self.node_name) if tree is not None else None
        if node is None or node.bl_idname != GROUP_IDNAME:
            self.report({'ERROR'}, 'Node group not found')
            return {'CANCELLED'}
        if node.node_tree is None:
            self.report({'ERROR'}, 'Node group has no inner tree')
            return {'CANCELLED'}
        node.sync_sockets()
        self.report({'INFO'},
                    f'{node.name}: {len(node.inputs)} in / {len(node.outputs)} out')
        return {'FINISHED'}


class BUFFERIO_OT_node_group_interface_add(Operator):
    """给当前正在编辑的节点组内部树添加一个接口端口"""
    bl_idname = 'bufferio.node_group_interface_add'
    bl_label = 'Add Group Interface'
    bl_options = {'REGISTER', 'UNDO'}

    in_out: EnumProperty(
        name='Direction',
        items=(('INPUT', 'Input', ''), ('OUTPUT', 'Output', '')),
        default='INPUT')
    socket_type: EnumProperty(
        name='Socket Type', items=SOCKET_TYPE_ITEMS, default='BufferIOSocketMesh')
    name: StringProperty(name='Name', default='Socket')
    description: StringProperty(name='Description', default='')
    tree_name: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        tree = _interface_tree(context, self.tree_name)
        if tree is None:
            self.report({'ERROR'}, 'No node tree is being edited')
            return {'CANCELLED'}
        name = self.name.strip() or 'Socket'
        existing = {item.name for item in tree.interface.items_tree}
        if name in existing:
            self.report({'ERROR'}, f'Socket "{name}" already exists')
            return {'CANCELLED'}
        tree.interface.new_socket(name, description=self.description,
                                  in_out=self.in_out,
                                  socket_type=self.socket_type)
        _refresh_owner_sockets(tree)
        return {'FINISHED'}


class BUFFERIO_OT_node_group_interface_remove(Operator):
    """删除当前节点组内部树的一个接口端口"""
    bl_idname = 'bufferio.node_group_interface_remove'
    bl_label = 'Remove Group Interface'
    bl_options = {'REGISTER', 'UNDO'}

    item_name: StringProperty()
    tree_name: StringProperty()

    def execute(self, context):
        tree = _interface_tree(context, self.tree_name)
        if tree is None:
            return {'CANCELLED'}
        item = next((entry for entry in tree.interface.items_tree
                     if entry.name == self.item_name), None)
        if item is None:
            self.report({'ERROR'}, 'Interface socket not found')
            return {'CANCELLED'}
        tree.interface.remove(item)
        _refresh_owner_sockets(tree)
        return {'FINISHED'}


class BUFFERIO_OT_node_group_interface_move(Operator):
    """在接口列表中上移 / 下移一个端口（顺序与原生节点组接口一致）"""
    bl_idname = 'bufferio.node_group_interface_move'
    bl_label = 'Move Group Interface'
    bl_options = {'REGISTER', 'UNDO'}

    item_name: StringProperty()
    tree_name: StringProperty()
    delta: IntProperty(default=-1, min=-1, max=1)

    def execute(self, context):
        tree = _interface_tree(context, self.tree_name)
        if tree is None:
            return {'CANCELLED'}
        items = list(tree.interface.items_tree)
        index = next((i for i, entry in enumerate(items)
                      if entry.name == self.item_name), None)
        if index is None:
            self.report({'ERROR'}, 'Interface socket not found')
            return {'CANCELLED'}
        target = index + self.delta
        if not 0 <= target < len(items):
            return {'CANCELLED'}
        tree.interface.move(items[index], target)
        _refresh_owner_sockets(tree)
        return {'FINISHED'}


class BUFFERIO_OT_node_add(Operator):
    bl_idname = 'bufferio.node_add'
    bl_label = 'Add Node'
    bl_options = {'REGISTER', 'UNDO'}

    node_type: EnumProperty(name='Node Type', items=NODE_ADD_ENUM)

    def execute(self, context):
        tree = _active_tree(context)
        if tree is None:
            self.report({'ERROR'}, 'No BufferIO node tree is active')
            return {'CANCELLED'}

        node = tree.nodes.new(self.node_type)
        space = getattr(context, 'space_data', None)
        cursor = getattr(space, 'cursor_location', None)
        if cursor is not None:
            node.location = (cursor.x, cursor.y)
        else:
            right = max((n.location.x for n in tree.nodes), default=0.0)
            node.location = (right + 260.0, 0.0)

        for other in tree.nodes:
            other.select = False
        node.select = True
        tree.nodes.active = node
        return {'FINISHED'}


# 可用 +/- 按钮增减输入端口数量的装配节点 -> 计数属性
SLOT_COUNT_PROPERTIES = {
    'BufferIOMeshAssemble': 'array_count',
}


class BUFFERIO_OT_assemble_slot(Operator):
    bl_idname = 'bufferio.assemble_slot'
    bl_label = 'Adjust Assemble Slots'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()
    delta: IntProperty(default=1, min=-1, max=1)

    def execute(self, context):
        tree = _active_tree(context)
        node = tree.nodes.get(self.node_name) if tree is not None else None
        prop = SLOT_COUNT_PROPERTIES.get(node.bl_idname) if node else None
        if prop is None:
            self.report({'ERROR'}, 'Assemble node not found')
            return {'CANCELLED'}

        setattr(node, prop,
                max(1, min(64, getattr(node, prop) + self.delta)))
        node.rebuild_sockets()
        return {'FINISHED'}


class BUFFERIO_OT_node_bake(Operator):
    bl_idname = 'bufferio.node_bake'
    bl_label = 'Import'
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty(name='Output Node')

    def execute(self, context):
        tree = _active_tree(context)
        if tree is None:
            self.report({'ERROR'}, 'No BufferIO node tree is active')
            return {'CANCELLED'}

        ctx = EvaluationContext(context, tree)
        if self.node_name:
            node = tree.nodes.get(self.node_name)
            if node is None or node.bl_idname != 'BufferIOOutput':
                self.report({'ERROR'}, 'Import node not found')
                return {'CANCELLED'}
            ctx.evaluate_node(node)
        else:
            try:
                ctx.evaluate_outputs()
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}

        for node_name, message in ctx.errors:
            self.report({'ERROR'}, f'{node_name}: {message}')
        if ctx.errors:
            return {'CANCELLED'}
        return {'FINISHED'}


class BUFFERIO_PT_node_sidebar(Panel):
    """节点编辑器侧边栏：节点树管理与一键导入入口"""
    bl_label = 'BufferIO'
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'BufferIO'

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        tree = space.edit_tree

        if tree is None or tree.bl_idname != 'BufferIONodeTree':
            layout.label(text='No BufferIO node tree is being edited', icon='INFO')
            col = layout.column(align=True)
            col.operator('bufferio.node_new_tree', icon='ADD')
            col.operator('bufferio.node_open_tree', icon='FILE_FOLDER')
            return

        owner_node = tree.get('bufferio_owner_node')
        if owner_node:
            layout.label(text=f'Inner node group: {owner_node}', icon='NODETREE')
            layout.operator('bufferio.node_group_exit', icon='BACK')
            layout.label(text='Press Tab to return to the parent')
            layout.separator()

        layout.operator('bufferio.node_import_fmt', icon='IMPORT')
        layout.separator()

        # 选中组节点：无需进入内部即可编辑接口，并手动同步外部端口
        active = tree.nodes.active
        if active is not None and active.bl_idname == 'BufferIOGroup':
            box = layout.box()
            box.label(text=f'Selected group: {active.name}', icon='NODETREE')
            row = box.row(align=True)
            op = row.operator('bufferio.node_group_enter', text='Edit Interior',
                              icon='NODETREE')
            op.node_name = active.name
            op = row.operator('bufferio.node_group_sync', text='Sync Ports',
                              icon='AUTO')
            op.node_name = active.name
            if active.node_tree is not None:
                self.draw_interface(layout, active.node_tree)

        # 节点组内部：允许直接增删接口端口（外部端口在返回父级时同步）
        inner_owner = _owner_node(tree)
        if inner_owner is not None and inner_owner.bl_idname == 'BufferIOGroup':
            self.draw_interface(layout, tree)

        col = layout.column(align=True)
        col.operator('bufferio.node_new_tree', icon='ADD')

    @staticmethod
    def draw_interface(layout, tree):
        box = layout.box()
        box.label(text=f'Group Interface: {tree.name}', icon='NODETREE')
        box.prop(tree, 'name', text='Group Name')
        for item in tree.interface.items_tree:
            direction = getattr(item, 'in_out', '')
            if direction not in {'INPUT', 'OUTPUT'}:
                continue
            row = box.row(align=True)
            row.label(text='In' if direction == 'INPUT' else 'Out')
            row.prop(item, 'name', text='')
            op = row.operator('bufferio.node_group_interface_move',
                              icon='TRIA_UP', text='')
            op.item_name = item.name
            op.tree_name = tree.name
            op.delta = -1
            op = row.operator('bufferio.node_group_interface_move',
                              icon='TRIA_DOWN', text='')
            op.item_name = item.name
            op.tree_name = tree.name
            op.delta = 1
            op = row.operator('bufferio.node_group_interface_remove',
                              icon='REMOVE', text='')
            op.item_name = item.name
            op.tree_name = tree.name
            # 端口类型 + 描述（与原生 Group Interface 面板一致，可直接编辑）
            sub = box.row(align=True)
            sub.scale_y = 0.75
            sub.label(text=getattr(item, 'socket_type', '').replace(
                'BufferIOSocket', '') or 'Any')
            sub.prop(item, 'description', text='')
        row = box.row(align=True)
        op = row.operator('bufferio.node_group_interface_add', text='+ Input', icon='ADD')
        op.in_out = 'INPUT'
        op.tree_name = tree.name
        op = row.operator('bufferio.node_group_interface_add', text='+ Output', icon='ADD')
        op.in_out = 'OUTPUT'
        op.tree_name = tree.name


def register_menus():
    bpy.types.NODE_MT_add.append(_draw_add_menu)


def unregister_menus():
    try:
        bpy.types.NODE_MT_add.remove(_draw_add_menu)
    except Exception:
        pass


CLASSES = (
    BUFFERIO_OT_node_new_tree,
    BUFFERIO_OT_node_open_tree,
    BUFFERIO_OT_node_group_enter,
    BUFFERIO_OT_node_group_exit,
    BUFFERIO_OT_node_group_toggle,
    BUFFERIO_OT_node_group_make,
    BUFFERIO_OT_node_group_ungroup,
    BUFFERIO_OT_node_group_sync,
    BUFFERIO_OT_node_group_interface_add,
    BUFFERIO_OT_node_group_interface_remove,
    BUFFERIO_OT_node_group_interface_move,
    BUFFERIO_OT_node_add,
    BUFFERIO_OT_assemble_slot,
    BUFFERIO_OT_node_bake,
    BUFFERIO_PT_node_sidebar,
)
