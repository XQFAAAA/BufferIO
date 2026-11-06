"""BufferIO 节点系统注册入口。"""

from .sockets import CLASSES as SOCKET_CLASSES
from .tree import BufferIONodeTree
from .element_desc import BUFFERIO_NODE_vb_element_desc
from .element_semantic import BUFFERIO_NODE_element_semantic
from .index_buffer import BUFFERIO_NODE_index_buffer
from .bone_matrix import BUFFERIO_NODE_bone_matrix
from .shape_key import BUFFERIO_NODE_shape_key
from .shape_key_apply import BUFFERIO_NODE_shape_key_apply
from .assemble import BUFFERIO_NODE_mesh_assemble
from .output import BUFFERIO_NODE_output_mesh
from .value import CLASSES as VALUE_CLASSES
from .group import CLASSES as GROUP_CLASSES
from .ui import CLASSES as NODE_UI_CLASSES
from .ui import register_menus, unregister_menus

# 注册顺序：Socket -> NodeTree -> Node -> UI
CLASSES = (
    *SOCKET_CLASSES,
    BufferIONodeTree,
    BUFFERIO_NODE_vb_element_desc,
    BUFFERIO_NODE_element_semantic,
    BUFFERIO_NODE_index_buffer,
    BUFFERIO_NODE_bone_matrix,
    BUFFERIO_NODE_shape_key,
    BUFFERIO_NODE_shape_key_apply,
    BUFFERIO_NODE_mesh_assemble,
    BUFFERIO_NODE_output_mesh,
    *VALUE_CLASSES,
    *GROUP_CLASSES,
    *NODE_UI_CLASSES,
)

__all__ = ('CLASSES', 'register_menus', 'unregister_menus')
