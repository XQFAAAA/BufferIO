"""BufferIO：将 vb、ib 等渲染资源缓冲导入 Blender。

插件入口模块：负责 Scene 属性定义与所有子模块的注册/注销。
子模块划分（按职责）：
    constants    —— 语义枚举、坐标轴、目录
    properties   —— FMT 解析为轻量元素对象（导入时一次性使用）
    core         —— 校验、顶点数组收集、网格对象构建与链接
    operators    —— 从 FMT 生成节点（节点框内自动装配）
    nodes        —— 节点式编辑器的 Tree / Socket / Node / 求值器 / 面板
    storage      —— 底层二进制读取（mmap 缓存）、索引解析与顶点压缩
    buffer_io    —— 网格 / 骨架对象构建
    dxgi         —— DXGI 格式定义
    fmt_parser   —— fmt / 3dmigoto txt 解析与资源发现

入口只有节点编辑器：侧栏「Import from FMT」生成节点框，
节点链最终由 Import 节点烘焙出网格与骨架。
"""

import bpy
import os
from bpy.props import PointerProperty

from .nodes import CLASSES as NODE_CLASSES
from .nodes import register_menus as register_node_menus
from .nodes import unregister_menus as unregister_node_menus
from .nodes.tree import BufferIONodeTree
from .operators import CLASSES as OPERATOR_CLASSES

# 插件根目录（含 presets/）：操作符 bl_options 含 'PRESET'，Blender 会在
# 「Import from FMT」右侧自动绘制原生预设行；预设目录为
# presets/operator/bufferio.node_import_fmt/（内置 WuWa 预设随插件分发）
PRESET_ROOT = os.path.dirname(__file__)

bl_info = {
    'name': 'BufferIO',
    'author': 'BufferIO',
    'version': (1, 4, 0),
    'blender': (5, 2, 0),
    'location': 'Node Editor > BufferIO',
    'description': 'Import render resource buffers such as vb / ib into Blender 5.2',
    'category': 'Import-Export',
}

# 注册顺序：节点系统（Socket/Tree/Node）-> 操作符
CLASSES = (
    *NODE_CLASSES,
    *OPERATOR_CLASSES,
)

# 需要在 Scene 上注册的属性（unregister 时按此顺序清理）
# 只保留节点编辑器当前编辑的树；其余导入参数都在节点上
SCENE_PROPERTIES = (
    ('bufferio_node_tree', PointerProperty, {'type': BufferIONodeTree}),
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    register_node_menus()

    for name, prop_cls, kwargs in SCENE_PROPERTIES:
        setattr(bpy.types.Scene, name, prop_cls(**kwargs))

    # 注册插件根目录作为预设搜索根（bpy.utils.preset_paths 会在根目录下
    # 查找 presets/<subdir>），让「Import from FMT」右侧的预设菜单能看到 WuWa
    bpy.utils.register_preset_path(PRESET_ROOT)


def unregister():
    try:
        bpy.utils.unregister_preset_path(PRESET_ROOT)
    except ValueError:
        pass

    unregister_node_menus()

    for name, _, _ in SCENE_PROPERTIES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
