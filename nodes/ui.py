"""BufferIO 节点编辑器操作符、侧边栏面板与 Shift+A 添加菜单。"""

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator, Panel

from .evaluator import EvaluationContext

# 节点类型 -> (标签, 图标)，顺序即 Shift+A 菜单中的顺序
NODE_ADD_ITEMS = (
    ('BufferIOIndexBuffer', 'Index Buffer', 'SNAP_VERTEX',
     'Read an index buffer (file or ib txt) and output an index socket'),
    ('BufferIOGenericBuffer', 'Vertex Buffer', 'TEXT',
     'Read an arbitrary vertex buffer and tag a semantic'),
    ('BufferIOBoneMatrix', 'Bone Matrix', 'BONE_DATA', 'Read bone skinning matrices'),
    ('BufferIOShapeKey', 'ShapeKey Resource', 'SHAPEKEY_DATA',
     'Read a set of segmented shape key data'),
    ('BufferIOShapeKeyApply', 'ShapeKey Assemble', 'SHAPEKEY_DATA',
     'Append shape key groups to a mesh by slots (mesh + shape keys -> mesh)'),
    ('BufferIOMeshAssemble', 'Mesh Assemble', 'MESH_DATA', 'Assemble indices and vertex attributes'),
    ('BufferIOImport', 'Import', 'OBJECT_DATA',
     'Import mesh and/or bone matrices (only matrices = armature only)'),
    ('BufferIOValueFormat', 'Format', 'PROPERTIES', 'Output a DXGI format value'),
    ('BufferIOValueString', 'String', 'FONT_DATA', 'Output a string value'),
    ('BufferIOValueFloat', 'Float', 'DRIVER', 'Output a float value'),
    ('BufferIOValueInt', 'Int', 'LINENUMBERS_ON', 'Output an int value'),
    ('BufferIOValueBool', 'Bool', 'CHECKBOX_HLT', 'Output a bool value'),
)


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
    """Shift+A / 交换菜单注入 BufferIO 节点（走官方 node.add_node 体系，
    自动获得节点搜索、拖拽连线插入与鼠标落点变换）"""
    space = getattr(context, 'space_data', None)
    tree_type = getattr(space, 'tree_type', '') if space is not None else ''
    if tree_type != 'BufferIONodeTree':
        return
    layout = self.layout
    for idname, label, _icon, _description in NODE_ADD_ITEMS:
        self.node_operator(layout, idname, label=label)


# 可用 +/- 按钮增减输入端口数量的装配节点 -> 计数属性
SLOT_COUNT_PROPERTIES = {
    'BufferIOMeshAssemble': 'array_count',
    'BufferIOShapeKeyApply': 'shape_count',
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

    node_name: StringProperty(name='Import Node')

    def execute(self, context):
        tree = _active_tree(context)
        if tree is None:
            self.report({'ERROR'}, 'No BufferIO node tree is active')
            return {'CANCELLED'}

        ctx = EvaluationContext(context, tree)
        if self.node_name:
            node = tree.nodes.get(self.node_name)
            if node is None or node.bl_idname != 'BufferIOImport':
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
    """节点编辑器侧边栏：仅保留 FMT 导入入口

    树的新建/打开由节点编辑器标题栏原生按钮完成；
    仅在 BufferIO 节点树类型的编辑器中显示。
    """
    bl_label = 'BufferIO'
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'BufferIO'

    @classmethod
    def poll(cls, context):
        space = getattr(context, 'space_data', None)
        return (space is not None and space.type == 'NODE_EDITOR'
                and getattr(space, 'tree_type', '') == 'BufferIONodeTree')

    def draw(self, context):
        layout = self.layout
        layout.operator('bufferio.node_import_fmt', icon='IMPORT')
        layout.operator('bufferio.node_bake', text='Import All',
                        icon='FILE_REFRESH')


def register_menus():
    # 同时挂到添加与交换菜单（与官方模板一致，支持 Shift+A 搜索与节点交换）
    bpy.types.NODE_MT_add.append(_draw_add_menu)
    bpy.types.NODE_MT_swap.append(_draw_add_menu)


def unregister_menus():
    for menu in (bpy.types.NODE_MT_add, bpy.types.NODE_MT_swap):
        try:
            menu.remove(_draw_add_menu)
        except Exception:
            pass


CLASSES = (
    BUFFERIO_OT_assemble_slot,
    BUFFERIO_OT_node_bake,
    BUFFERIO_PT_node_sidebar,
)
