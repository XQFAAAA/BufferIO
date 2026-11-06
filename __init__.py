"""BufferIO：将 vb、ib 等渲染资源缓冲导入 Blender。

插件入口模块：负责 Scene 属性定义与所有子模块的注册/注销。
子模块划分（按职责）：
    constants    —— 语义枚举、坐标轴、目录
    properties   —— 元素数据模型与 fmt 解析填充（侧面板与节点共用）
    core         —— 校验、顶点数组收集、网格对象构建与链接
    operators    —— 侧面板与节点编辑器的全部操作符
    ui           —— 3D 视图侧边栏面板与元素列表
    nodes        —— 节点式编辑器的 Tree / Socket / Node / 求值器 / 面板
    storage      —— 底层二进制读取（mmap 缓存）、索引解析与顶点压缩
    buffer_io    —— 网格 / 骨架对象构建
    dxgi         —— DXGI 格式定义
    fmt_parser   —— fmt / 3dmigoto txt 解析与资源发现

双入口：
    1. 3D 视图侧边栏（元素列表工作流，经典导入）
    2. 节点编辑器（VB ELEMENT DESC -> 网格装配 -> Import）
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .constants import AXIS_ITEMS
from .nodes import CLASSES as NODE_CLASSES
from .nodes import register_menus as register_node_menus
from .nodes import unregister_menus as unregister_node_menus
from .nodes.tree import BufferIONodeTree
from .operators import CLASSES as OPERATOR_CLASSES
from .properties import BufferIOElement
from .ui import CLASSES as UI_CLASSES

bl_info = {
    'name': 'BufferIO',
    'author': 'BufferIO',
    'version': (1, 3, 0),
    'blender': (5, 2, 0),
    'location': '3D View Sidebar / Node Editor > BufferIO',
    'description': 'Import render resource buffers such as vb / ib into Blender 5.2',
    'category': 'Import-Export',
}

# 注册顺序：PropertyGroup -> 节点系统（Socket/Tree/Node）-> UIList/Operator -> Panel
CLASSES = (
    BufferIOElement,
    *NODE_CLASSES,
    *UI_CLASSES,
    *OPERATOR_CLASSES,
)

# 需要在 Scene 上注册的属性（unregister 时按此顺序清理）
SCENE_PROPERTIES = (
    ('bufferio_node_tree', PointerProperty, {'type': BufferIONodeTree}),
    ('bufferio_elements', CollectionProperty, {'type': BufferIOElement}),
    ('bufferio_elements_index', IntProperty, {'default': 0}),
    ('bufferio_fmt_path', StringProperty, {
        'name': 'FMT File', 'subtype': 'FILE_PATH',
        'description': '.fmt file or 3dmigoto FrameAnalysis vb txt file path',
    }),
    ('bufferio_fmt_info', StringProperty, {'default': ''}),
    ('bufferio_ib_file', StringProperty, {'default': ''}),
    ('bufferio_ib_format', StringProperty, {'default': 'R16_UINT'}),
    ('bufferio_ib_offset', IntProperty, {'default': 0}),
    ('bufferio_ib_first', IntProperty, {'default': 0}),
    ('bufferio_ib_count', IntProperty, {'default': 0}),
    ('bufferio_flip_winding', BoolProperty, {
        'name': 'Flip Winding', 'default': True,
        'description': 'Reverse the triangle vertex order (a different order changes the face normal direction)',
    }),
    ('bufferio_flip_texcoord_v', BoolProperty, {
        'name': 'Flip UV V Axis', 'default': True,
    }),
    ('bufferio_global_scale', FloatProperty, {
        'name': 'Global Scale', 'default': 0.01, 'min': 0.0001, 'max': 1000.0,
        'description': 'Global scale factor for vertex coordinates (e.g. 0.01 to convert WuWa game units to meters)',
    }),
    ('bufferio_mirror_x', BoolProperty, {
        'name': 'Mirror (X Axis)', 'default': False,
        'description': 'Mirror the mesh along the X axis, flipping normals / tangents and the winding direction as well',
    }),
    ('bufferio_axis_forward', EnumProperty, {
        'name': 'Forward Axis', 'items': AXIS_ITEMS, 'default': 'Y',
        'description': 'Forward axis of the source resource',
    }),
    ('bufferio_axis_up', EnumProperty, {
        'name': 'Up Axis', 'items': AXIS_ITEMS, 'default': 'Z',
        'description': 'Up axis of the source resource',
    }),
    # 面板展开/收起控制
    ('bufferio_show_options', BoolProperty, {'name': 'Transform Options', 'default': True}),
    ('bufferio_show_item', BoolProperty, {'name': 'Element Properties', 'default': True}),
)


addon_keymaps = []


def _register_group_timer():
    """组节点端口实时同步（模拟原生节点组：面板/接口变化后端口自动更新）"""
    from .nodes.group import sync_all_groups

    if bpy.app.timers.is_registered(sync_all_groups):
        bpy.app.timers.unregister(sync_all_groups)
    bpy.app.timers.register(sync_all_groups, first_interval=0.6,
                            persistent=True)


def _unregister_group_timer():
    from .nodes.group import sync_all_groups

    if bpy.app.timers.is_registered(sync_all_groups):
        bpy.app.timers.unregister(sync_all_groups)


def _register_keymaps():
    """Tab 进入/退出节点组，Ctrl+G 编组，Ctrl+Alt+G 解组"""
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon if wm is not None else None
    if kc is None:
        return
    km = kc.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')
    addon_keymaps.append((km, km.keymap_items.new(
        'bufferio.node_group_toggle', 'TAB', 'PRESS')))
    addon_keymaps.append((km, km.keymap_items.new(
        'bufferio.node_group_make', 'G', 'PRESS', ctrl=True)))
    addon_keymaps.append((km, km.keymap_items.new(
        'bufferio.node_group_ungroup', 'G', 'PRESS', ctrl=True, alt=True)))


def _unregister_keymaps():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    register_node_menus()
    _register_keymaps()
    _register_group_timer()

    for name, prop_cls, kwargs in SCENE_PROPERTIES:
        setattr(bpy.types.Scene, name, prop_cls(**kwargs))


def unregister():
    _unregister_group_timer()
    _unregister_keymaps()
    unregister_node_menus()

    for name, _, _ in SCENE_PROPERTIES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
