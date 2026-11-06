"""BufferIO 自定义节点树类型。"""

import bpy


class BufferIONodeTree(bpy.types.NodeTree):
    bl_idname = 'BufferIONodeTree'
    bl_label = 'BufferIO'
    bl_icon = 'MESH_DATA'
    bl_description = 'BufferIO buffer import node tree'
