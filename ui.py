"""BufferIO UI：列表（UIList）与主面板（Panel）。"""

import bpy
from bpy.types import Panel, UIList

from . import dxgi


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
        # 目标语义在左，格式在右（格式下拉按语义推荐置顶）；原始语义/索引见元素属性面板
        sub.prop(item, 'semantic', text='')
        sub.prop(item, 'format', text='')


class BUFFERIO_PT_main(Panel):
    bl_label = 'BufferIO'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BufferIO'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        self.draw_import_mode(layout, scene)

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
        layout.operator('bufferio.import_fmt', icon='IMPORT')

    def draw_import_mode(self, layout, scene):
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
                recommended = [name for name in dxgi.SEMANTIC_FORMATS.get(item.semantic, ())
                               if name in dxgi.SUPPORTED_FORMATS]
                if recommended:
                    box.label(text='推荐格式: ' + ' / '.join(recommended))
                box.prop(item, 'stride')
                box.prop(item, 'offset')
                box.prop(item, 'count')
                box.prop(item, 'byte_offset')


CLASSES = (
    BUFFERIO_UL_elements,
    BUFFERIO_PT_main,
)
