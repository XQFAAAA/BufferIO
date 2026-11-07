"""BufferIO 自定义节点树类型。"""

import bpy
from bpy.props import BoolProperty


def _update_use_category_color(self, context):
    """切换分类配色：应用到树内全部节点（关闭时还原主题色）"""
    for node in self.nodes:
        if self.use_category_color:
            node.use_custom_color = True
            node.color = getattr(node, 'CATEGORY_COLOR', (0.16, 0.20, 0.26))
        else:
            node.use_custom_color = False


class BufferIONodeTree(bpy.types.NodeTree):
    bl_idname = 'BufferIONodeTree'
    bl_label = 'BufferIO'
    bl_icon = 'MESH_DATA'
    bl_description = 'BufferIO buffer import node tree'

    # 分类配色开关（默认关闭：与原生节点一致跟随主题，可在侧栏开启）
    use_category_color: BoolProperty(
        name='Category Color',
        description='Apply per-category colors to nodes (off = follow the theme)',
        default=False,
        update=_update_use_category_color,
    )

    def update(self):
        """连线变化：Pull 式求值无需重建，仅清掉遗留的错误摘要，
        避免修好连线后节点上仍显示过期的错误信息"""
        for node in self.nodes:
            info = node.get('info')
            if info and 'ERROR: ' in str(info):
                node['info'] = ''
