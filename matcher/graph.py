"""Matcher 的统一分子图契约和节点—边联合更新层。

配体与候选 A 都使用本文件的建图规则和层实现，但模型为两侧分别实例化参数。
图层计算式改编自 MIT 许可的 PocketXMol ``models/graph.py``；本项目只保留
``BondFFN``、``NodeBlock``、``EdgeBlock`` 和逐层残差更新，不包含坐标更新。
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn


@dataclass(frozen=True)
class MolecularGraph:
    """固定拓扑和原始边字段。

    ``edge_index`` 为 ``int64 [2,E]``，第一行是消息来源原子，第二行是目标原子。
    ``edge_input`` 为 ``float32 [E,31]``，字段顺序见 ``build_molecular_graph``。
    ``edge_class`` 为 ``int64 [E]``；0 表示纯 radius，1–5 表示五类化学键。
    """

    edge_index: Tensor
    edge_input: Tensor
    edge_class: Tensor


@dataclass(frozen=True)
class GraphState:
    """一个或多个互不相连图的动态状态。

    ``node [N,D_node]``、``edge [E,D_edge]``，``edge_index`` 为
    ``int64 [2,E]``，第一行是消息来源节点，第二行是目标节点。
    """

    node: Tensor
    edge: Tensor
    edge_index: Tensor


def _distance_rbf(distance: Tensor, radius: float, bins: int) -> Tensor:
    centers = torch.linspace(0.0, radius, bins, device=distance.device, dtype=distance.dtype)
    sigma = radius / (bins - 1)
    return torch.exp(-0.5 * ((distance[:, None] - centers[None]) / sigma) ** 2)


def build_molecular_graph(
    coordinates: Tensor,
    geometry_group: Tensor,
    chemical_edge_index: Tensor,
    bond_order: Tensor,
    bond_role: Tensor,
    ring_size: Tensor,
    *,
    radius: float = 4.0,
    max_radius_neighbors: int = 48,
    rbf_bins: int = 16,
) -> MolecularGraph:
    """构造化学键与局部 radius 邻接的有向并集。

    参数中的 ``coordinates`` 是 ``float [N,3]`` XYZ Å；``geometry_group`` 是
    ``int64 [N]``，只决定哪些原子共享可靠坐标系。化学边输入是每条无向边一次：
    ``chemical_edge_index [2,E_chemical]``、``bond_order [E_chemical,5]``、
    ``bond_role [E_chemical,3]`` 和 ``ring_size [E_chemical,4]``。

    返回的 31 维字段依次是五类键序、三类键角色、四类环、``is_chemical``、
    ``is_radius``、``distance_valid`` 和 16 维 0–4 Å 距离 RBF。跨几何组化学键
    保留，但距离字段为零。化学键与 radius 重合时只保留一个有向端点记录。
    """

    device = coordinates.device
    dtype = coordinates.dtype
    num_nodes = coordinates.shape[0]
    records: dict[tuple[int, int], Tensor] = {}

    if num_nodes:
        distances = torch.cdist(coordinates, coordinates)
        for target in range(num_nodes):
            valid = (
                (geometry_group == geometry_group[target])
                & (distances[:, target] <= radius)
                & (torch.arange(num_nodes, device=device) != target)
            )
            sources = torch.nonzero(valid, as_tuple=False).flatten()
            if sources.numel() > max_radius_neighbors:
                order = torch.argsort(distances[sources, target], stable=True)
                sources = sources[order[:max_radius_neighbors]]
            for source in sources.tolist():
                field = torch.zeros(15 + rbf_bins, device=device, dtype=dtype)
                field[13] = 1.0
                field[14] = 1.0
                field[15:] = _distance_rbf(
                    distances[source, target].reshape(1), radius, rbf_bins
                )[0]
                records[(source, target)] = field

    for edge_i in range(chemical_edge_index.shape[1]):
        left = int(chemical_edge_index[0, edge_i])
        right = int(chemical_edge_index[1, edge_i])
        for source, target in ((left, right), (right, left)):
            field = records.get((source, target))
            if field is None:
                field = torch.zeros(15 + rbf_bins, device=device, dtype=dtype)
            else:
                field = field.clone()
            field[:5] = bond_order[edge_i].to(dtype)
            field[5:8] = bond_role[edge_i].to(dtype)
            field[8:12] = ring_size[edge_i].to(dtype)
            field[12] = 1.0
            if geometry_group[source] == geometry_group[target]:
                distance = torch.linalg.vector_norm(coordinates[source] - coordinates[target])
                field[14] = 1.0
                field[15:] = _distance_rbf(distance.reshape(1), radius, rbf_bins)[0]
            records[(source, target)] = field

    if not records:
        return MolecularGraph(
            edge_index=torch.empty((2, 0), dtype=torch.long, device=device),
            edge_input=torch.empty((0, 15 + rbf_bins), dtype=dtype, device=device),
            edge_class=torch.empty((0,), dtype=torch.long, device=device),
        )

    ordered_pairs = sorted(records)
    edge_index = torch.tensor(ordered_pairs, dtype=torch.long, device=device).T.contiguous()
    edge_input = torch.stack([records[pair] for pair in ordered_pairs])
    chemical = edge_input[:, 12].bool()
    edge_class = torch.zeros(len(ordered_pairs), dtype=torch.long, device=device)
    edge_class[chemical] = edge_input[chemical, :5].argmax(dim=-1) + 1
    return MolecularGraph(edge_index, edge_input, edge_class)


def _scatter_sum(values: Tensor, index: Tensor, size: int) -> Tensor:
    output = values.new_zeros((size, values.shape[-1]))
    return output.index_add_(0, index, values)


class BondFFN(nn.Module):
    """以端点节点状态门控一条边的消息。"""

    def __init__(self, node_dim: int, edge_dim: int) -> None:
        super().__init__()
        hidden_dim = 2 * edge_dim
        self.edge_projection = nn.Linear(edge_dim, hidden_dim, bias=False)
        self.node_projection = nn.Linear(node_dim, hidden_dim, bias=False)
        self.message = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, edge_dim),
        )
        self.gate = nn.Sequential(
            nn.Linear(edge_dim + node_dim, 32),
            nn.LayerNorm(32),
            nn.ReLU(),
            nn.Linear(32, edge_dim),
        )

    def forward(self, edge: Tensor, endpoint: Tensor) -> Tensor:
        hidden = self.edge_projection(edge) * self.node_projection(endpoint)
        gate = torch.sigmoid(self.gate(torch.cat((edge, endpoint), dim=-1)))
        return self.message(hidden) * gate


class NodeBlock(nn.Module):
    """聚合边条件的来源节点消息，产生节点增量。"""

    def __init__(self, node_dim: int, edge_dim: int) -> None:
        super().__init__()
        self.source = nn.Sequential(
            nn.Linear(node_dim, node_dim),
            nn.LayerNorm(node_dim),
            nn.ReLU(),
            nn.Linear(node_dim, node_dim),
        )
        self.edge = nn.Sequential(
            nn.Linear(edge_dim, node_dim),
            nn.LayerNorm(node_dim),
            nn.ReLU(),
            nn.Linear(node_dim, node_dim),
        )
        self.message = nn.Linear(node_dim, node_dim)
        self.gate = nn.Sequential(
            nn.Linear(edge_dim + node_dim, node_dim),
            nn.LayerNorm(node_dim),
            nn.ReLU(),
            nn.Linear(node_dim, node_dim),
        )
        self.self_projection = nn.Linear(node_dim, node_dim)
        self.norm = nn.LayerNorm(node_dim)
        self.output = nn.Linear(node_dim, node_dim)

    def forward(self, state: GraphState) -> Tensor:
        source, target = state.edge_index
        source_node = state.node[source]
        message = self.message(self.edge(state.edge) * self.source(source_node))
        gate = torch.sigmoid(self.gate(torch.cat((state.edge, source_node), dim=-1)))
        message = message * gate
        aggregate = _scatter_sum(message, target, state.node.shape[0])
        hidden = self.norm(aggregate + self.self_projection(state.node))
        return self.output(torch.relu(hidden))


class EdgeBlock(nn.Module):
    """汇总有向边两端的相邻边环境，产生边增量。"""

    def __init__(self, node_dim: int, edge_dim: int) -> None:
        super().__init__()
        self.left_message = BondFFN(node_dim, edge_dim)
        self.right_message = BondFFN(node_dim, edge_dim)
        self.left_node = nn.Linear(node_dim, edge_dim)
        self.right_node = nn.Linear(node_dim, edge_dim)
        self.self_projection = nn.Linear(edge_dim, edge_dim)
        self.norm = nn.LayerNorm(edge_dim)
        self.output = nn.Linear(edge_dim, edge_dim)

    def forward(self, state: GraphState) -> Tensor:
        source, target = state.edge_index
        left_message = self.left_message(state.edge, state.node[source])
        right_message = self.right_message(state.edge, state.node[target])
        left_context = _scatter_sum(left_message, target, state.node.shape[0])[source]
        right_context = _scatter_sum(right_message, source, state.node.shape[0])[target]
        hidden = (
            left_context
            + right_context
            + self.left_node(state.node[source])
            + self.right_node(state.node[target])
            + self.self_projection(state.edge)
        )
        return self.output(torch.relu(self.norm(hidden)))


class NodeEdgeLayer(nn.Module):
    """从同一输入快照计算节点与边增量，再分别残差写回。"""

    def __init__(
        self, node_dim: int = 128, edge_dim: int = 64, *, update_edge: bool = True
    ) -> None:
        super().__init__()
        self.update_edge = update_edge
        self.node_block = NodeBlock(node_dim, edge_dim)
        self.edge_block = EdgeBlock(node_dim, edge_dim) if update_edge else None

    def forward(self, state: GraphState) -> GraphState:
        node_delta = self.node_block(state)
        edge = state.edge
        if self.edge_block is not None:
            edge = edge + self.edge_block(state)
        return GraphState(state.node + node_delta, edge, state.edge_index)
