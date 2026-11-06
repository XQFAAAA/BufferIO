"""节点间传递的轻量数据容器（只在求值期存在，不写入 RNA / .blend）。"""

from dataclasses import dataclass, field

import numpy


@dataclass
class ArrayData:
    """单个缓冲属性或索引面的数据"""
    values: numpy.ndarray
    semantic: str = ''
    index: int = 0
    format: str = ''
    source: str = ''
    meta: dict = field(default_factory=dict)


@dataclass
class ShapeKeyData:
    """一组分段形态键数据（抵消边界 + 顶点 id + 位移向量）"""
    offsets: numpy.ndarray
    vertex_ids: numpy.ndarray
    vertex_offsets: numpy.ndarray


@dataclass
class MeshData:
    """装配后的网格：三角形索引 + 顶点属性数组

    arrays 的键为 (semantic, semantic_index)，与 core.build_and_link 一致；
    faces 为 (n, 3) 顶点索引（可能为 None，表示按顶点顺序生成三角形）；
    vertex_map 为顶点压缩映射（vertex_map[原始编号] = 压缩后编号，未引用为 -1，
    None 表示未压缩），用于把形态键的原始顶点 id 重定向到压缩后的网格；
    bone_matrices 为 (n, 3, 4) 骨骼矩阵，shape_keys 为 ShapeKeyData 列表。
    """
    faces: object
    arrays: dict
    vertex_map: object = None
    bone_matrices: object = None
    shape_keys: list = field(default_factory=list)
