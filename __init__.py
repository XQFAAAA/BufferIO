"""BufferIO：将 vb、ib 等渲染资源缓冲导入 Blender。

插件入口模块：负责 Scene 属性定义与所有子模块的注册/注销。
子模块划分（按职责）：
    constants    —— 语义枚举、坐标轴、目录、动态枚举辅助
    properties   —— PropertyGroup 数据模型与属性更新回调
    core         —— 校验、顶点数组收集、网格构建与链接
    operators    —— 全部操作符
    ui           —— UIList 与主面板
    buffer_io    —— 底层二进制读取与网格对象构建
    dxgi         —— DXGI 格式定义
    fmt_parser   —— fmt / 3dmigoto txt 解析与资源发现
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from .constants import AXIS_ITEMS
from .operators import CLASSES as OPERATOR_CLASSES
from .properties import BufferIOElement
from .ui import CLASSES as UI_CLASSES

bl_info = {
    'name': 'BufferIO',
    'author': 'BufferIO',
    'version': (1, 0, 0),
    'blender': (4, 0, 0),
    'location': '3D 视图 > 侧边栏 > BufferIO',
    'description': '将 vb、ib 等渲染资源缓冲导入 Blender',
    'category': 'Import-Export',
}

# 注册顺序：PropertyGroup -> UIList/Operator -> Panel（依赖其类型）
CLASSES = (
    BufferIOElement,
    *UI_CLASSES,
    *OPERATOR_CLASSES,
)

# 需要在 Scene 上注册的属性（unregister 时按此顺序清理）
SCENE_PROPERTIES = (
    ('bufferio_elements', CollectionProperty, {'type': BufferIOElement}),
    ('bufferio_elements_index', IntProperty, {'default': 0}),
    ('bufferio_fmt_path', StringProperty, {
        'name': 'FMT 文件', 'subtype': 'FILE_PATH',
        'description': '.fmt 或 3dmigoto FrameAnalysis 的 vb txt 文件路径',
    }),
    ('bufferio_fmt_info', StringProperty, {'default': ''}),
    ('bufferio_ib_file', StringProperty, {'default': ''}),
    ('bufferio_ib_format', StringProperty, {'default': 'R16_UINT'}),
    ('bufferio_ib_offset', IntProperty, {'default': 0}),
    ('bufferio_ib_first', IntProperty, {'default': 0}),
    ('bufferio_ib_count', IntProperty, {'default': 0}),
    ('bufferio_flip_winding', BoolProperty, {
        'name': '翻转环绕方向', 'default': True,
        'description': '翻转三角形顶点顺序（不同的顺序会导致面法线方向不同）',
    }),
    ('bufferio_flip_texcoord_v', BoolProperty, {
        'name': '翻转 UV 的 V 轴', 'default': True,
    }),
    ('bufferio_global_scale', FloatProperty, {
        'name': '全局缩放', 'default': 0.01, 'min': 0.0001, 'max': 1000.0,
        'description': '顶点坐标全局缩放系数（如 WuWa 游戏单位转米可用 0.01）',
    }),
    ('bufferio_mirror_x', BoolProperty, {
        'name': '镜像（X 轴）', 'default': False,
        'description': '沿 X 轴镜像网格，并同步翻转法线/切线与环绕方向',
    }),
    ('bufferio_axis_forward', EnumProperty, {
        'name': '前方轴', 'items': AXIS_ITEMS, 'default': 'Y',
        'description': '源资源的朝前轴',
    }),
    ('bufferio_axis_up', EnumProperty, {
        'name': '上方轴', 'items': AXIS_ITEMS, 'default': 'Z',
        'description': '源资源的朝上轴',
    }),
    # 面板展开/收起控制
    ('bufferio_show_options', BoolProperty, {'name': '变换选项', 'default': True}),
    ('bufferio_show_item', BoolProperty, {'name': '元素属性', 'default': True}),
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    for name, prop_cls, kwargs in SCENE_PROPERTIES:
        setattr(bpy.types.Scene, name, prop_cls(**kwargs))


def unregister():
    for name, _, _ in SCENE_PROPERTIES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
