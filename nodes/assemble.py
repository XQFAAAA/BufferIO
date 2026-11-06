"""网格装配节点：把索引与任意数量的顶点属性数组组装为 MeshData。

输入插槽数量可变（数组插槽可用节点上的 +/− 按钮增减）；
各数组按自身携带的语义（ArrayData.semantic / index）自动归类，不再依赖固定的插槽名。
骨骼矩阵由 Bone Matrix 节点直接接到 Import 的 Matrix 输入，形态键由 ShapeKey Assemble 节点处理。
"""

import numpy
from bpy.props import IntProperty

from .. import buffer_io
from .base import BufferIONode
from .data import ArrayData, MeshData


class BUFFERIO_NODE_mesh_assemble(BufferIONode):
    bl_idname = 'BufferIOMeshAssemble'
    bl_label = 'Mesh Assemble'
    bl_description = 'Assemble indices and arbitrary vertex attribute arrays into mesh data by semantic'
    bl_icon = 'MESH_DATA'
    CATEGORY_COLOR = (0.16, 0.16, 0.24)

    array_count: IntProperty(name='Array Slots', default=8, min=1, max=64)

    def init(self, context):
        super().init(context)
        self._build_inputs()
        self.add_output('BufferIOSocketMesh', 'Mesh')

    def _build_inputs(self):
        self.add_input('BufferIOSocketIndex', 'Index')
        for i in range(self.array_count):
            self.add_input('BufferIOSocketArray', f'ELEMENT[{i}]')

    def rebuild_sockets(self):
        """按当前插槽数量重建输入插槽，并保留仍然存在的连线

        连线按「Socket 类型 + 同类序号」记录，插槽改名（Array N -> ELEMENT[N]）
        或增减数量时不会丢连线。
        """
        links = []
        counts = {}
        for socket in self.inputs:
            order = counts.get(socket.bl_idname, 0)
            counts[socket.bl_idname] = order + 1
            for link in socket.links:
                links.append((link.from_node.name, link.from_socket.name,
                              socket.bl_idname, order))
        while len(self.inputs):
            self.inputs.remove(self.inputs[0])
        self._build_inputs()

        tree = self.id_data
        groups = {}
        for socket in self.inputs:
            groups.setdefault(socket.bl_idname, []).append(socket)
        for from_node_name, from_socket_name, idname, order in links:
            targets = groups.get(idname, [])
            if order >= len(targets):
                continue
            source = tree.nodes.get(from_node_name)
            from_socket = source.outputs.get(from_socket_name) if source else None
            if from_socket is not None:
                tree.links.new(from_socket, targets[order])

    def evaluate(self, ctx):
        arrays = {}
        faces = None

        for socket in self.inputs:
            data = ctx.input(self, socket.name)
            if data is None or not isinstance(data, ArrayData):
                continue
            values = numpy.ascontiguousarray(data.values)
            if data.semantic == 'INDEX':
                if values.size % 3 != 0:
                    raise ValueError(
                        f'Index count {values.size} is not a multiple of 3')
                faces = numpy.ascontiguousarray(values.reshape(-1, 3))
            else:
                arrays[(data.semantic, data.index)] = values

        if not any(semantic == 'POSITION' for semantic, _ in arrays):
            raise ValueError('No POSITION array connected')

        # compact_vertices 会切片并重排索引，之后必须从压缩后的 arrays 取值
        faces, arrays, vertex_map = buffer_io.compact_vertices(faces, arrays)

        triangles = len(faces) if faces is not None else 0
        vertices = len(next(iter(arrays.values()))) if arrays else 0
        names = ' '.join(f'{semantic}{index or ""}'
                         for semantic, index in sorted(arrays))
        if len(names) > 46:
            names = names[:44] + '…'
        self.set_info([
            f'Vertices {vertices}  Triangles {triangles}',
            f'Arrays {names}',
        ])

        return {'Mesh': MeshData(faces=faces, arrays=arrays, vertex_map=vertex_map)}

    def draw_buttons(self, context, layout):
        row = layout.row(align=True)
        op = row.operator('bufferio.assemble_slot', text='+ Array', icon='ADD')
        op.node_name = self.name
        op.delta = 1
        op = row.operator('bufferio.assemble_slot', text='- Array', icon='REMOVE')
        op.node_name = self.name
        op.delta = -1

        self.draw_info(layout)
