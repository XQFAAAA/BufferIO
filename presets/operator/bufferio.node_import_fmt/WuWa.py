# Blender operator preset for BufferIO "Import from FMT"
# Wuthering Waves: ATTRIBUTE n -> POSITION / TANGENT / NORMAL /
# TEXCOORD 0-3 / COLOR / blend attributes
# 与原生操作项预设一致（AddPresetOperator）：op = bpy.context.active_operator
import bpy

op = bpy.context.active_operator

op.use_mapping = True
op.attributes.clear()
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 0
item_sub_1.semantic = 'POSITION'
item_sub_1.target_index = 0
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 1
item_sub_1.semantic = 'TANGENT'
item_sub_1.target_index = 1
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 2
item_sub_1.semantic = 'NORMAL'
item_sub_1.target_index = 2
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 3
item_sub_1.semantic = 'BLENDINDICES'
item_sub_1.target_index = 3
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 4
item_sub_1.semantic = 'BLENDWEIGHTS'
item_sub_1.target_index = 4
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 5
item_sub_1.semantic = 'TEXCOORD'
item_sub_1.target_index = 0
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 6
item_sub_1.semantic = 'TEXCOORD'
item_sub_1.target_index = 1
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 7
item_sub_1.semantic = 'TEXCOORD'
item_sub_1.target_index = 2
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 8
item_sub_1.semantic = 'TEXCOORD'
item_sub_1.target_index = 3
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 13
item_sub_1.semantic = 'COLOR'
item_sub_1.target_index = 0
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 14
item_sub_1.semantic = 'BLENDINDICES'
item_sub_1.target_index = 14
item_sub_1 = op.attributes.add()
item_sub_1.semantic_name = 'ATTRIBUTE'
item_sub_1.semantic_index = 15
item_sub_1.semantic = 'BLENDWEIGHTS'
item_sub_1.target_index = 15
op.search_shape_keys = True
op.bone_matrix_tag = 'vs-cb4'
