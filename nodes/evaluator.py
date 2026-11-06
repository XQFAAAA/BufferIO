"""Pull 式节点求值器：从输出节点反向拉取，单次求值内 memo 化。"""


class EvaluationError(Exception):
    pass


def _find_socket(collection, name):
    for socket in collection:
        if socket.name == name:
            return socket
    return None


def active_link(socket):
    """取第一个参与求值的连线：被禁用（is_muted）或失效的连线视为未连接"""
    if socket is None:
        return None
    for link in socket.links:
        if not link.is_muted and link.is_valid:
            return link
    return None


def active_links(socket):
    """取多输入端口上全部参与求值的连线，按拖动顺序排列"""
    if socket is None:
        return []
    links = sorted(socket.links, key=lambda link: link.multi_input_sort_id)
    return [link for link in links if not link.is_muted and link.is_valid]


class EvaluationContext:
    def __init__(self, context, tree, group_inputs=None, group_stack=()):
        self.context = context
        self.tree = tree
        self.memo = {}
        self.visiting = set()
        self.errors = []  # [(节点名, 错误信息)]
        # 节点组内部求值时，NodeGroupInput 端口对应的外部输入值
        self.group_inputs = group_inputs or {}
        # 当前求值所处的节点组内部树栈（as_pointer），用于检测自引用/循环编组
        self.group_stack = tuple(group_stack)

    def input(self, node, socket_name):
        """拉取某个输入 Socket 连接上游的结果（禁用的连线不参与）"""
        link = active_link(_find_socket(node.inputs, socket_name))
        if link is None:
            return None
        result = self.evaluate_node(link.from_node)
        return result.get(link.from_socket.name)

    def evaluate_node(self, node):
        key = node.as_pointer()
        if key in self.memo:
            return self.memo[key]
        if key in self.visiting:
            raise EvaluationError(f'Cycle detected in node links: {node.name}')

        self.visiting.add(key)
        result = {}
        try:
            if node.bl_idname == 'NodeGroupInput':
                # 组输入节点：直接使用外层注入的端口值
                result = {socket.name: self.group_inputs.get(socket.name)
                          for socket in node.outputs}
            else:
                result = node.evaluate(self) or {}
        except Exception as exc:
            self.errors.append((node.name, str(exc)))
            # 把错误直接留在节点上（节点下一次求值成功时会被结果摘要覆盖）
            set_info = getattr(node, 'set_info', None)
            if set_info is not None:
                try:
                    set_info([f'ERROR: {exc}'])
                except Exception:
                    pass
        finally:
            self.visiting.discard(key)

        self.memo[key] = result
        return result

    def evaluate_outputs(self):
        outputs = [n for n in self.tree.nodes
                   if n.bl_idname == 'BufferIOOutput']
        if not outputs:
            raise EvaluationError('The node tree has no output node')
        for node in outputs:
            self.evaluate_node(node)
        return outputs
