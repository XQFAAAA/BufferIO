"""通用节点组：框选节点后 Ctrl+G 合并为一个可 Tab 进入的子节点组。

实现要点：
- 选中节点被克隆到新建的内部 BufferIONodeTree（属性与内部连线一并复制）；
- 跨越选区的连线转化为组的输入/输出接口项（NodeGroupInput / NodeGroupOutput）；
- 外层生成 BufferIOGroup 节点，端口按内部树接口自动同步，并按原位置重连；
- 节点组在求值时用内部树求值，NodeGroupInput 的端口值由外层连线注入。
"""

import copy

import bpy
from bpy.props import PointerProperty

from .base import BufferIONode
from .evaluator import EvaluationContext, active_link
from .tree import BufferIONodeTree

GROUP_IDNAME = 'BufferIOGroup'
GROUP_INPUT_IDNAME = 'NodeGroupInput'
GROUP_OUTPUT_IDNAME = 'NodeGroupOutput'
# 组输入/输出节点本身不参与编组
GROUP_IO_IDNAMES = frozenset({GROUP_INPUT_IDNAME, GROUP_OUTPUT_IDNAME})

# 支持「未连线时可填默认值」的标量端口类型 -> 初始值
# （自定义 Socket 不带原生 default_value，这里按实例存进节点 ID 属性）
SCALAR_SOCKET_DEFAULTS = {
    'BufferIOSocketFloat': 0.0,
    'BufferIOSocketInt': 0,
    'BufferIOSocketBool': False,
    'BufferIOSocketString': '',
    'BufferIOSocketFormat': '',
}
DEFAULT_KEY_PREFIX = 'bufferio_default:'

# 这些属性属于 Blender 内置 Node，克隆时由创建/位置逻辑处理，不复制
BUILTIN_PROPERTIES = frozenset(
    set(bpy.types.Node.bl_rna.properties.keys()) | {'rna_type'}
)

# 自定义属性中不需要克隆的（端口映射会按接口重新生成）
SKIPPED_IDPROPS = frozenset({'bufferio_socket_ids', 'info', 'cloning'})


def _copy_props(src, dst):
    """复制节点的自定义 RNA 属性与 ID 属性（集合/指针单独处理）"""
    dst['cloning'] = True
    try:
        for prop in src.bl_rna.properties:
            ident = prop.identifier
            if ident in BUILTIN_PROPERTIES or prop.is_readonly:
                continue
            if prop.type in {'COLLECTION', 'POINTER'}:
                continue
            try:
                setattr(dst, ident, getattr(src, ident))
            except Exception:
                pass
        for key in src.keys():
            if key == '_RNA_UI' or key in SKIPPED_IDPROPS:
                continue
            try:
                dst[key] = copy.deepcopy(src[key])
            except Exception:
                pass
        # 内置视觉属性不随 RNA 循环复制，这里补上，保持编组后的外观一致
        try:
            dst.label = src.label
            dst.mute = src.mute
            dst.hide = src.hide
            dst.use_custom_color = src.use_custom_color
            dst.color = src.color
        except Exception:
            pass
        try:
            dst.width = src.width
            dst.height = src.height
        except Exception:
            pass
    finally:
        try:
            del dst['cloning']
        except Exception:
            pass


def _copy_tree_pointer(src, dst):
    """克隆节点组 / 资源描述节点的内部节点树指针

    通用节点组按实例共享同一棵内部树；资源描述节点的内部树各自独立，
    浅共享会让内外两层投影互相覆盖，因此必须复制一份。
    """
    src_tree = getattr(src, 'node_tree', None)
    if src_tree is None or not hasattr(dst, 'node_tree'):
        return
    dst_tree = getattr(dst, 'node_tree', None)
    if src.bl_idname == 'BufferIOSourceFile':
        tree = src_tree.copy()
        tree.name = f'{src_tree.name} Inner'
        tree.use_fake_user = True
        # 复制后的内部树归新节点所有，否则 Tab 进入时会跳回原节点
        tree['bufferio_owner_tree'] = dst.id_data.name
        tree['bufferio_owner_node'] = dst.name
    else:
        tree = src_tree
    dst.node_tree = tree
    # 丢弃节点 init 时自动创建的空树，避免残留
    if dst_tree is not None and dst_tree.as_pointer() != tree.as_pointer():
        try:
            bpy.data.node_groups.remove(dst_tree)
        except Exception:
            pass


def _copy_elements(src, dst):
    """复制资源描述节点的外部元素列表（旧版节点没有内部树时使用）"""
    dst['syncing'] = True
    try:
        dst.elements.clear()
        for item in src.elements:
            new = dst.elements.add()
            for prop in item.bl_rna.properties:
                ident = prop.identifier
                if ident == 'rna_type' or prop.is_readonly:
                    continue
                try:
                    setattr(new, ident, getattr(item, ident))
                except Exception:
                    pass
    finally:
        try:
            del dst['syncing']
        except Exception:
            pass


def _post_clone(src, dst):
    """克隆后的收尾：描述节点按内部树重建端口，动态插槽节点重建插槽"""
    if dst.bl_idname == 'BufferIOSourceFile':
        from .element_desc import (GROUP_OUTPUT_IDNAME, rebuild_internal,
                                   refresh_from_internal)
        tree = getattr(dst, 'node_tree', None)
        if tree is not None and any(node.bl_idname == GROUP_OUTPUT_IDNAME
                                    for node in tree.nodes):
            refresh_from_internal(dst)  # 内部树已存在：按内部节点回填外部列表
        else:
            _copy_elements(src, dst)
            rebuild_internal(dst)  # 旧版节点：按外部列表补建内部树
        return
    if dst.bl_idname == GROUP_IDNAME:
        dst.sync_sockets()  # 组节点端口按内部树接口重建
        return
    if hasattr(dst, 'rebuild_sockets'):
        dst.rebuild_sockets()


def _match_sockets(src_sockets, dst_sockets):
    """按名称把源节点 Socket 映射到克隆节点 Socket（返回 {源指针: 目标 Socket}）"""
    remaining = list(dst_sockets)
    mapping = {}
    for socket in src_sockets:
        found = next((i for i, other in enumerate(remaining)
                      if other.name == socket.name), None)
        if found is None:
            continue
        mapping[socket.as_pointer()] = remaining.pop(found)
    return mapping


def ensure_inner(node):
    """确保组节点拥有一棵内部树，并补齐组输入 / 组输出节点（手动新建空组时使用）"""
    inner = node.node_tree
    if inner is None:
        inner = bpy.data.node_groups.new('Node Group', 'BufferIONodeTree')
        inner.use_fake_user = True
        node.node_tree = inner

    content = [n for n in inner.nodes if n.bl_idname not in GROUP_IO_IDNAMES]
    left = min((n.location.x for n in content), default=0.0) - 260.0
    right = max((n.location.x for n in content), default=0.0) + 260.0
    if not any(n.bl_idname == GROUP_INPUT_IDNAME for n in inner.nodes):
        gin = inner.nodes.new(GROUP_INPUT_IDNAME)
        gin.location = (left, 0.0)
    if not any(n.bl_idname == GROUP_OUTPUT_IDNAME for n in inner.nodes):
        gout = inner.nodes.new(GROUP_OUTPUT_IDNAME)
        gout.location = (right, 0.0)
    return inner


def make_group(tree):
    """把当前选中节点合并为节点组，返回新的组节点；没有选中节点返回 None"""
    selected = [node for node in tree.nodes
                if node.select and node.bl_idname not in GROUP_IO_IDNAMES]
    if not selected:
        return None
    pointers = {node.as_pointer() for node in selected}

    inner = bpy.data.node_groups.new('Node Group', 'BufferIONodeTree')
    inner.use_fake_user = True

    clones = {}
    for src in selected:
        dst = inner.nodes.new(src.bl_idname)
        dst.location = src.location
        _copy_props(src, dst)
        _copy_tree_pointer(src, dst)
        clones[src.as_pointer()] = dst

    socket_maps = {}
    for src in selected:
        dst = clones[src.as_pointer()]
        _post_clone(src, dst)
        socket_maps[src.as_pointer()] = (
            _match_sockets(src.inputs, dst.inputs),
            _match_sockets(src.outputs, dst.outputs),
        )

    # 分析连线：内部连线复制进组，跨越选区的连线转成接口
    inner_links = []
    boundary_inputs = []   # (外层输出 Socket, 组内输入 Socket)
    boundary_outputs = []  # (组内输出 Socket, 外层输入 Socket)
    for link in tree.links:
        from_sel = link.from_node.as_pointer() in pointers
        to_sel = link.to_node.as_pointer() in pointers
        if from_sel and to_sel:
            src_socket = socket_maps[link.from_node.as_pointer()][1].get(
                link.from_socket.as_pointer())
            dst_socket = socket_maps[link.to_node.as_pointer()][0].get(
                link.to_socket.as_pointer())
            if src_socket is not None and dst_socket is not None:
                inner_links.append((src_socket, dst_socket))
        elif to_sel and not from_sel:
            dst_socket = socket_maps[link.to_node.as_pointer()][0].get(
                link.to_socket.as_pointer())
            if dst_socket is not None:
                boundary_inputs.append((link.from_socket, dst_socket))
        elif from_sel and not to_sel:
            src_socket = socket_maps[link.from_node.as_pointer()][1].get(
                link.from_socket.as_pointer())
            if src_socket is not None:
                boundary_outputs.append((src_socket, link.to_socket))

    # 接口项：名称跨输入/输出去重
    used_names = set()

    def unique_name(base):
        name, index = base, 2
        while name in used_names:
            name = f'{base}.{index:03d}'
            index += 1
        used_names.add(name)
        return name

    in_items = []   # (接口名, 外层输出 Socket, 组内输入 Socket)
    for outer_socket, dst_socket in boundary_inputs:
        socket_type = dst_socket.bl_idname
        if socket_type == 'NodeSocketVirtual':
            continue
        name = unique_name(dst_socket.name)
        inner.interface.new_socket(name, in_out='INPUT', socket_type=socket_type)
        in_items.append((name, outer_socket, dst_socket))

    out_items = []  # (接口名, 外层输入 Socket 列表, 组内输出 Socket)
    out_seen = {}
    for src_socket, outer_socket in boundary_outputs:
        socket_type = src_socket.bl_idname
        if socket_type == 'NodeSocketVirtual':
            continue
        key = src_socket.as_pointer()
        if key in out_seen:
            out_seen[key][1].append(outer_socket)
            continue
        name = unique_name(src_socket.name)
        inner.interface.new_socket(name, in_out='OUTPUT', socket_type=socket_type)
        entry = [name, [outer_socket], src_socket]
        out_seen[key] = entry
        out_items.append(entry)

    # 组输入/组输出节点 + 内部连线
    min_x = min(node.location.x for node in selected)
    max_x = max(node.location.x for node in selected)
    center_y = sum(node.location.y for node in selected) / len(selected)
    gin = inner.nodes.new(GROUP_INPUT_IDNAME)
    gin.location = (min_x - 240.0, center_y)
    gout = inner.nodes.new(GROUP_OUTPUT_IDNAME)
    gout.location = (max_x + 240.0, center_y)

    for name, _outer, dst_socket in in_items:
        source = gin.outputs.get(name)
        if source is not None:
            inner.links.new(source, dst_socket)
    for name, _outer, src_socket in out_items:
        target = gout.inputs.get(name)
        if target is not None:
            inner.links.new(src_socket, target)
    for src_socket, dst_socket in inner_links:
        inner.links.new(src_socket, dst_socket)

    # 外层组节点与接口端口
    group = tree.nodes.new(GROUP_IDNAME)
    group.node_tree = inner
    group.location = (min_x, center_y)
    group.sync_sockets()  # 名称与端口都按内部树同步（不再手工写 label）

    # 删除原节点，并按接口名恢复外部连线
    for node in selected:
        tree.nodes.remove(node)

    for name, outer_socket, _dst in in_items:
        target = group.inputs.get(name)
        if target is not None and outer_socket is not None:
            tree.links.new(outer_socket, target)
    for name, outer_sockets, _src in out_items:
        source = group.outputs.get(name)
        if source is None:
            continue
        for outer_socket in outer_sockets:
            if outer_socket is not None:
                tree.links.new(source, outer_socket)

    return group


def ungroup(tree, node):
    """把节点组节点展开回外层树（内部节点、内部连线与接口连线一并还原）

    返回是否执行成功；内部树在展开后删除。
    """
    if node.bl_idname != GROUP_IDNAME or node.node_tree is None:
        return False
    inner = node.node_tree

    # 记录组节点与外层的连线（按接口名）
    outer_inputs = {}
    for socket in node.inputs:
        for link in socket.links:
            outer_inputs.setdefault(socket.name, []).append(link.from_socket)
    outer_outputs = {}
    for socket in node.outputs:
        for link in socket.links:
            outer_outputs.setdefault(socket.name, []).append(link.to_socket)

    offset_x, offset_y = node.location.x, node.location.y
    sockets = {}
    for src in inner.nodes:
        if src.bl_idname in GROUP_IO_IDNAMES:
            continue
        dst = tree.nodes.new(src.bl_idname)
        dst.location = (src.location.x + offset_x, src.location.y + offset_y)
        _copy_props(src, dst)
        _copy_tree_pointer(src, dst)
        _post_clone(src, dst)
        sockets[src.as_pointer()] = (
            _match_sockets(src.inputs, dst.inputs),
            _match_sockets(src.outputs, dst.outputs),
        )

    def targets_of(node_ptr):
        return sockets.get(node_ptr, ({}, {}))[0]

    def sources_of(node_ptr):
        return sockets.get(node_ptr, ({}, {}))[1]

    for link in list(inner.links):
        if link.from_node.bl_idname == GROUP_INPUT_IDNAME:
            # 组输入接口 -> 外层来源
            dst_socket = targets_of(link.to_node.as_pointer()).get(
                link.to_socket.as_pointer())
            if dst_socket is not None:
                for source in outer_inputs.get(link.from_socket.name, ()):
                    tree.links.new(source, dst_socket)
        elif link.to_node.bl_idname == GROUP_OUTPUT_IDNAME:
            # 组输出接口 -> 外层目标
            src_socket = sources_of(link.from_node.as_pointer()).get(
                link.from_socket.as_pointer())
            if src_socket is not None:
                for target in outer_outputs.get(link.to_socket.name, ()):
                    tree.links.new(src_socket, target)
        else:
            src_socket = sources_of(link.from_node.as_pointer()).get(
                link.from_socket.as_pointer())
            dst_socket = targets_of(link.to_node.as_pointer()).get(
                link.to_socket.as_pointer())
            if src_socket is not None and dst_socket is not None:
                tree.links.new(src_socket, dst_socket)

    tree.nodes.remove(node)
    # 通用节点组的内部树按实例共享：还有别的组节点在用就保留
    if inner.users == 0:
        try:
            bpy.data.node_groups.remove(inner)
        except Exception:
            pass
    return True


class BUFFERIO_NODE_group(BufferIONode):
    bl_idname = GROUP_IDNAME
    bl_label = 'Node Group'
    bl_description = 'Generic node group: select nodes and press Ctrl+G to create, Tab to edit the interior'
    bl_icon = 'NODETREE'
    CATEGORY_COLOR = (0.14, 0.18, 0.28)

    def _on_tree_update(self, context):
        """在节点上切换内部树后立即按接口重建端口"""
        try:
            self.sync_sockets()
        except Exception:
            pass

    node_tree: PointerProperty(type=BufferIONodeTree, name='Inner Node Group',
                               update=_on_tree_update)

    def init(self, context):
        super().init(context)

    # --- 外部端口 <-> 内部接口 ---------------------------------------

    def sync_sockets(self):
        """按内部树接口同步外部端口，并按名称恢复已有连线

        接口没变化时直接返回：避免每次求值 / 绘制都全量重建端口与连线。
        """
        inner = self.node_tree
        if inner is None:
            return

        # 名称跟随内部树（与材质/几何节点组一致）：未手改名或名称为旧树名时自动同步
        inner_name = inner.name
        prev_name = str(self.get('bufferio_tree_name') or '')
        if prev_name != inner_name:
            self['bufferio_tree_name'] = inner_name
            if not self.label or self.label == prev_name:
                self.label = inner_name

        wanted_inputs = [(item.name, item.socket_type)
                         for item in inner.interface.items_tree
                         if getattr(item, 'in_out', '') == 'INPUT']
        wanted_outputs = [(item.name, item.socket_type)
                          for item in inner.interface.items_tree
                          if getattr(item, 'in_out', '') == 'OUTPUT']
        current_inputs = [(socket.name, socket.bl_idname) for socket in self.inputs]
        current_outputs = [(socket.name, socket.bl_idname) for socket in self.outputs]
        if current_inputs == wanted_inputs and current_outputs == wanted_outputs:
            return

        # 记录连线：优先按名称匹配，名称找不到（接口重命名）时退回同序号端口
        saved_inputs = [(order, socket.name, socket.links[0].from_socket)
                        for order, socket in enumerate(self.inputs) if socket.is_linked]
        saved_outputs = [(order, socket.name, link.to_socket)
                         for order, socket in enumerate(self.outputs)
                         for link in socket.links]

        while len(self.inputs):
            self.inputs.remove(self.inputs[0])
        while len(self.outputs):
            self.outputs.remove(self.outputs[0])

        for name, socket_type in wanted_inputs:
            try:
                self.inputs.new(socket_type, name)
            except Exception:
                continue
            # 自定义 Socket 没有原生 default_value：为标量端口预置实例默认值
            if socket_type in SCALAR_SOCKET_DEFAULTS:
                key = f'{DEFAULT_KEY_PREFIX}{name}'
                if key not in self.keys():
                    try:
                        self[key] = SCALAR_SOCKET_DEFAULTS[socket_type]
                    except Exception:
                        pass
        for name, socket_type in wanted_outputs:
            try:
                self.outputs.new(socket_type, name)
            except Exception:
                pass

        # 清理已删除接口留下的默认值键
        wanted_names = {name for name, _ in wanted_inputs}
        for key in list(self.keys()):
            if (key.startswith(DEFAULT_KEY_PREFIX)
                    and key[len(DEFAULT_KEY_PREFIX):] not in wanted_names):
                try:
                    del self[key]
                except Exception:
                    pass

        outer_tree = self.id_data
        for order, name, from_socket in saved_inputs:
            target = self.inputs.get(name)
            if target is None and order < len(self.inputs):
                target = self.inputs[order]
            if target is not None and from_socket is not None:
                outer_tree.links.new(from_socket, target)
        for order, name, to_socket in saved_outputs:
            source = self.outputs.get(name)
            if source is None and order < len(self.outputs):
                source = self.outputs[order]
            if source is not None:
                outer_tree.links.new(source, to_socket)

    # --- 组输入默认值（替代原生 Socket 的 default_value） --------------

    @staticmethod
    def _default_path(socket_name):
        key = f'{DEFAULT_KEY_PREFIX}{socket_name}'
        escaped = key.replace('\\', '\\\\').replace('"', '\\"')
        return f'["{escaped}"]'

    def socket_default(self, socket_name):
        """取未连线组输入端口上填写的默认值；未填写（0/空）返回 None"""
        key = f'{DEFAULT_KEY_PREFIX}{socket_name}'
        if key not in self.keys():
            return None
        value = self[key]
        # 空字符串 / 0 / False 视为未填写，交给内部节点用自身属性兜底
        if isinstance(value, str):
            return value or None
        if isinstance(value, bool):
            return value or None
        if isinstance(value, (int, float)):
            return value if value else None
        return None

    def draw_socket_default(self, layout, socket, text):
        """由 Socket.draw 回调：组输入端口未连线时绘制实例默认值控件"""
        if socket.is_output or socket.is_linked:
            return False
        key = f'{DEFAULT_KEY_PREFIX}{socket.name}'
        if key not in self.keys():
            return False
        layout.prop(self, self._default_path(socket.name), text=text)
        return True

    # --- 求值 --------------------------------------------------------

    def evaluate(self, ctx):
        inner = self.node_tree
        if inner is None:
            raise ValueError('Node group has no inner node tree')
        # 自引用或 A→B→A 循环编组会在内部求值时无限递归，这里直接报错
        if inner.as_pointer() in ctx.group_stack:
            raise ValueError(f'Recursive node group: {inner.name}')

        group_inputs = {}
        for socket in self.inputs:
            if active_link(socket) is not None:
                group_inputs[socket.name] = ctx.input(self, socket.name)
            else:
                # 未连线时用端口上填写的默认值（与原生组输入行为一致）
                value = self.socket_default(socket.name)
                if value is not None:
                    group_inputs[socket.name] = value

        inner_ctx = EvaluationContext(
            ctx.context, inner, group_inputs,
            group_stack=ctx.group_stack + (inner.as_pointer(),))
        gout = next((node for node in inner.nodes
                     if node.bl_idname == GROUP_OUTPUT_IDNAME), None)
        if gout is None:
            self.set_info([f'ERROR: {inner.name} 缺少 Group Output'])
            raise ValueError('Node group is missing a Group Output node')

        results = {}
        for socket in gout.inputs:
            link = active_link(socket)
            if link is None:
                continue
            value = inner_ctx.evaluate_node(link.from_node).get(
                link.from_socket.name)
            if value is not None:
                results[socket.name] = value

        ctx.errors.extend(inner_ctx.errors)
        lines = [inner.name, f'Nodes {len(inner.nodes)}  Outputs {len(results)}']
        if inner_ctx.errors:
            lines.append(f'ERROR: {inner_ctx.errors[0][0]}: {inner_ctx.errors[0][1]}')
        self.set_info(lines)
        return results

    def draw_buttons(self, context, layout):
        col = layout.column(align=True)
        # 与原生节点组一致：节点上直接显示并切换内部节点组（数据块选择器）
        col.prop(self, 'node_tree', text='Tree')
        if self.node_tree is not None:
            col.label(text=f'{len(self.inputs)} in / {len(self.outputs)} out')
        else:
            col.label(text='No inner node group yet', icon='INFO')
        row = layout.row(align=True)
        op = row.operator('bufferio.node_group_enter', text='Edit Interior',
                          icon='NODETREE')
        op.node_name = self.name
        op = row.operator('bufferio.node_group_ungroup', text='Ungroup',
                          icon='UNLINKED')
        op.node_name = self.name
        row = layout.row(align=True)
        op = row.operator('bufferio.node_group_sync', text='Sync Ports',
                          icon='AUTO')
        op.node_name = self.name
        self.draw_info(layout)


def sync_all_groups():
    """定时把所有组节点端口对齐内部树接口

    自定义节点没有原生节点组的「端口即接口」机制，用轻量轮询模拟
    材质/几何节点组的实时效果：在内部增删/改名接口后，外层组节点
    无需 Tab 进出即可更新端口（接口未变化时 sync_sockets 直接短路）。
    """
    for tree in bpy.data.node_groups:
        if tree.bl_idname != 'BufferIONodeTree':
            continue
        for node in tree.nodes:
            if node.bl_idname != GROUP_IDNAME or node.node_tree is None:
                continue
            try:
                node.sync_sockets()
            except Exception:
                pass
    return 0.6


CLASSES = (BUFFERIO_NODE_group,)
