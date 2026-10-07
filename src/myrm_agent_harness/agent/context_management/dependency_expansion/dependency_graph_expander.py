# [POS] myrm_agent_harness/agent/context_management/dependency_expansion/dependency_graph_expander.py
# [INPUT] ArchitectureNode, ArchitectureNodeType, DependencyEdge, DependencyEdgeType, DependencyGraphExpansionResult
# [OUTPUT] ArchitecturalDependencyGraphExpander

"""全链路跨栈架构依赖展开图谱引擎，级联追踪 UI 组件到底层模型与历史架构决议。"""

from __future__ import annotations

import threading
from collections import deque

from .types import (
    ArchitectureNode,
    ArchitectureNodeType,
    DependencyEdge,
    DependencyEdgeType,
    DependencyGraphExpansionResult,
)


class ArchitecturalDependencyGraphExpander:
    """跨栈全链路架构依赖展开拓扑图引擎。

    解决传统代码跳转无法穿透前端组件到后端路由与数据库模型、
    以及无法关联历史已定案约束的深层次断层痛点。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, ArchitectureNode] = {}
        # source_id -> list[DependencyEdge]
        self._adjacency: dict[str, list[DependencyEdge]] = {}

    def add_node(self, node: ArchitectureNode) -> None:
        """注册或更新架构拓扑节点。"""
        with self._lock:
            self._nodes[node.node_id] = node
            if node.node_id not in self._adjacency:
                self._adjacency[node.node_id] = []

    def add_edge(self, edge: DependencyEdge) -> None:
        """添加拓扑关联依赖边。"""
        with self._lock:
            if edge.source_id not in self._adjacency:
                self._adjacency[edge.source_id] = []
            self._adjacency[edge.source_id].append(edge)

    def get_node(self, node_id: str) -> ArchitectureNode | None:
        """获取单个架构节点。"""
        with self._lock:
            return self._nodes.get(node_id)

    def expand_dependencies(
        self, node_id: str, max_depth: int = 3
    ) -> DependencyGraphExpansionResult:
        """从指定目标节点出发，级联展开关联的跨栈依赖并计算影响面得分。"""
        with self._lock:
            target_node = self._nodes.get(node_id)
            if not target_node:
                return DependencyGraphExpansionResult(
                    target_node_id=node_id,
                    visited_nodes=[],
                    blast_radius_score=0.0,
                    critical_constraints=[],
                    rejected_alternatives=[],
                    formatted_expansion_block="",
                )

            # BFS 级联拓扑展开
            queue: deque[tuple[str, int]] = deque([(node_id, 0)])
            visited_ids: set[str] = {node_id}
            ordered_nodes: list[ArchitectureNode] = [target_node]
            constraints: list[str] = []
            rejections: list[str] = []
            total_blast_score: float = 0.0

            node_weights: dict[ArchitectureNodeType, float] = {
                ArchitectureNodeType.COMPONENT: 8.0,
                ArchitectureNodeType.DEPENDENCY: 5.0,
                ArchitectureNodeType.API: 18.0,
                ArchitectureNodeType.DATA_MODEL: 25.0,
                ArchitectureNodeType.ARCHITECTURAL_DECISION: 12.0,
            }

            while queue:
                current_id, depth = queue.popleft()
                if depth >= max_depth:
                    continue

                for edge in self._adjacency.get(current_id, []):
                    neighbor_id = edge.target_id
                    neighbor_node = self._nodes.get(neighbor_id)
                    if not neighbor_node:
                        continue

                    # 收集约束与被否决反模式
                    if edge.edge_type == DependencyEdgeType.CONSTRAINED_BY:
                        constraints.append(
                            f"[{neighbor_node.name}] {neighbor_node.description} (关联自 {current_id})"
                        )
                    elif edge.edge_type == DependencyEdgeType.REJECTED_ALTERNATIVE:
                        rejections.append(
                            f"⛔ [{neighbor_node.name}] {neighbor_node.description} (已被否决，严禁采用)"
                        )

                    if neighbor_id not in visited_ids:
                        visited_ids.add(neighbor_id)
                        ordered_nodes.append(neighbor_node)
                        queue.append((neighbor_id, depth + 1))

                        # 影响面得分随深度衰减
                        decay = 1.0 / (depth + 1)
                        w = node_weights.get(neighbor_node.node_type, 5.0)
                        total_blast_score += w * decay

            normalized_blast = min(100.0, round(total_blast_score, 1))
            formatted_block = self._format_expansion_block(
                target_node, ordered_nodes, constraints, rejections, normalized_blast
            )

            return DependencyGraphExpansionResult(
                target_node_id=node_id,
                visited_nodes=ordered_nodes,
                blast_radius_score=normalized_blast,
                critical_constraints=constraints,
                rejected_alternatives=rejections,
                formatted_expansion_block=formatted_block,
            )

    def _format_expansion_block(
        self,
        target_node: ArchitectureNode,
        nodes: list[ArchitectureNode],
        constraints: list[str],
        rejections: list[str],
        blast_score: float,
    ) -> str:
        """结构化渲染依赖图谱与变更影响面提示词块。"""
        lines: list[str] = [
            "<architectural_dependency_graph>",
            f"<!-- 目标节点: {target_node.name} ({target_node.node_type.value}) | 变更影响面得分 (Blast Radius): {blast_score}/100 -->",
            "### 1. 级联跨栈关联实体 [DEPENDENCY TOPOLOGY]",
        ]

        for n in nodes:
            file_hint = f" ({n.file_path})" if n.file_path else ""
            lines.append(f"- **{n.name}** [{n.node_type.value}]{file_hint}: {n.description}")

        if constraints:
            lines.append("### 2. 关键架构硬约束 [GOVERNING CONSTRAINTS]")
            for c in constraints:
                lines.append(f"- ⚠️ {c}")

        if rejections:
            lines.append("### 3. 被否决方案与反模式警示 [REJECTED ALTERNATIVES - DO NOT RETRY]")
            for r in rejections:
                lines.append(f"- {r}")

        lines.append("</architectural_dependency_graph>")
        return "\n".join(lines)
