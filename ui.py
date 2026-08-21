"""BufferIO UI：列表（UIList）与主面板（Panel）。"""

from pathlib import Path

import bpy
from bpy.types import Panel, UIList

from .constants import INDEXED_SEMANTICS


class BUFFERIO_UL_attributes(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type not in {'DEFAULT', 'COMPACT'}:
            return
        row = layout.row(align=True)
        row.prop(item, 'enabled', text='')
        # 校验状态图标：0 正常 / 1 红(ERROR) / 2 黄(QUESTION)
        icon = 'FAKE_USER_ON' if item.warning == 0 else ('ERROR' if item.warning == 1 else 'QUESTION')
        row.label(text='', icon=icon)
        # 名称（单击选中，双击编辑）
        row.prop(item, 'export_name', text='', emboss=False)
        sub = row.row(align=True)
        sub.active = item.enabled
        # 语义下拉，可直接切换
        sub.prop(item, 'semantic', text='')
        row.label(text=Path(item.filepath).name if item.filepath else '<未指定文件>',
                  icon='FILE_BLANK')


class BUFFERIO_UL_elements(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type not in {'DEFAULT', 'COMPACT'}:
            return
        row = layout.row(align=True)
        row.prop(item, 'enabled', text='')
        # 校验状态图标：0 正常 / 1 红(ERROR) / 2 黄(QUESTION)
        icon = 'FAKE_USER_ON' if item.warning == 0 else ('ERROR' if item.warning == 1 else 'QUESTION')
        row.label(text='', icon=icon)
        # 名称（单击选中，双击编辑）
        row.prop(item, 'name', text='', emboss=False)
        sub = row.row(align=True)
        sub.active = item.enabled
        # 格式选择放在原始语义的左边（与下方属性栏共用）
        sub.prop(item, 'format', text='')
        sub.prop(item, 'semantic_name', text='')
        if item.semantic_index > 0 or item.semantic_name != 'INDEX':
            sub.prop(item, 'semantic_index', text='')
        sub.prop(item, 'semantic', text='')


class BUFFERIO_PT_main(Panel):
    bl_label = 'BufferIO'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BufferIO'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, 'bufferio_mode', expand=True)

        if scene.bufferio_mode == 'MESH':
            self.draw_mesh_mode(layout, scene)
        else:
            self.draw_fmt_mode(layout, scene)

        box = layout.box()
        row = box.row()
        row.prop(scene, 'bufferio_show_options', emboss=False,
                 icon='TRIA_DOWN' if scene.bufferio_show_options else 'TRIA_RIGHT',
                 text='变换选项')
        if scene.bufferio_show_options:
            box.prop(scene, 'bufferio_flip_winding')
            box.prop(scene, 'bufferio_flip_texcoord_v')
            box.separator()
            box.prop(scene, 'bufferio_mirror_x')
            box.prop(scene, 'bufferio_global_scale')
            row = box.row(align=True)
            row.label(text='坐标轴')
            row.prop(scene, 'bufferio_axis_forward', text='前')
            row.prop(scene, 'bufferio_axis_up', text='上')

        # 导入按钮统一放在面板最下方
        if scene.bufferio_mode == 'MESH':
            layout.operator('bufferio.import_mesh', icon='IMPORT')
        else:
            layout.operator('bufferio.import_fmt', icon='IMPORT')

    def draw_mesh_mode(self, layout, scene):
        row = layout.row()
        row.template_list('BUFFERIO_UL_attributes', '', scene, 'bufferio_attributes',
                          scene, 'bufferio_attributes_index', rows=4)
        col = row.column(align=True)
        col.operator('bufferio.attribute_add', icon='ADD', text='')
        col.operator('bufferio.attribute_remove', icon='REMOVE', text='')
        col.separator()
        col.operator('bufferio.attribute_move', icon='TRIA_UP', text='').direction = 'UP'
        col.operator('bufferio.attribute_move', icon='TRIA_DOWN', text='').direction = 'DOWN'
        # 保存/加载预设（不含文件路径，仅语义、索引、格式、步长、偏移）
        col.separator()
        col.operator('bufferio.save_mesh_preset', icon='EXPORT', text='')
        col.operator('bufferio.load_mesh_preset', icon='IMPORT', text='')
        col.separator()
        col.operator('bufferio.fa_paths', icon='FILE_FOLDER', text='')
        col.separator()
        col.operator('bufferio.validate_all', icon='ZOOM_ALL', text='')

        index = scene.bufferio_attributes_index
        if 0 <= index < len(scene.bufferio_attributes):
            item = scene.bufferio_attributes[index]
            box = layout.box()
            row = box.row()
            row.prop(scene, 'bufferio_show_item', emboss=False,
                     icon='TRIA_DOWN' if scene.bufferio_show_item else 'TRIA_RIGHT')
            if scene.bufferio_show_item:
                # 属性与索引同一行
                row = box.row(align=True)
                row.prop(item, 'semantic', text='')
                if item.semantic in INDEXED_SEMANTICS:
                    row.prop(item, 'semantic_index', text='')
                box.prop(item, 'filepath')
                if item.semantic == 'INDEX':
                    box.prop(item, 'ib_txt')
                    box.prop(item, 'first_index')
                    box.prop(item, 'index_count')
                box.prop(item, 'format')
                box.prop(item, 'stride')
                box.prop(item, 'offset')
                box.prop(item, 'count')

    def draw_fmt_mode(self, layout, scene):
        row = layout.row()
        row.template_list('BUFFERIO_UL_elements', '', scene, 'bufferio_elements',
                          scene, 'bufferio_elements_index', rows=6)
        col = row.column(align=True)
        col.operator('bufferio.element_add', icon='ADD', text='')
        col.operator('bufferio.element_remove', icon='REMOVE', text='')
        col.separator()
        col.operator('bufferio.element_move', icon='TRIA_UP', text='').direction = 'UP'
        col.operator('bufferio.element_move', icon='TRIA_DOWN', text='').direction = 'DOWN'
        # 保存/加载元素预设（不含文件路径）
        col.separator()
        col.operator('bufferio.save_semantics', icon='EXPORT', text='')
        col.operator('bufferio.load_semantics', icon='IMPORT', text='')
        col.separator()
        col.operator('bufferio.load_fmt', icon='FILE_FOLDER', text='')
        col.separator()
        col.operator('bufferio.validate_all', icon='ZOOM_ALL', text='')

        index = scene.bufferio_elements_index
        if 0 <= index < len(scene.bufferio_elements):
            item = scene.bufferio_elements[index]
            box = layout.box()
            row = box.row()
            row.prop(scene, 'bufferio_show_item', emboss=False,
                     icon='TRIA_DOWN' if scene.bufferio_show_item else 'TRIA_RIGHT')
            if scene.bufferio_show_item:
                # 第一行：SemanticName、SemanticIndex、属性、索引
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
                box.prop(item, 'stride')
                box.prop(item, 'offset')
                box.prop(item, 'count')


CLASSES = (
    BUFFERIO_UL_attributes,
    BUFFERIO_UL_elements,
    BUFFERIO_PT_main,
)
