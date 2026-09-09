"""Topological Evidence Tree implementation for structured working memory.

[INPUT]
- toolkits.memory.working_tree.models::EvidenceNode (POS: 强类型树状工作记忆原子节点)
- toolkits.memory.working_tree.models::EvidenceNodeStatus (POS: 证据节点生命周期状态枚举)
- toolkits.memory.working_tree.models::BoundedSummary (POS: 严格有界摘要与核心实体指标容器)
- toolkits.memory.working_tree.models::EvidenceSource (POS: 溯源信息容器)

[OUTPUT]
- EvidenceTree: 有向无环因果图容器，支持拓扑遍历、子树投影与 KV Cache 前缀时序装配

[POS]
ReTree 拓扑证据树容器。维护证据因果依赖 DAG，提供祖先回溯、派生追踪与低带宽提示词切片生成。
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from .models import BoundedSummary, EvidenceNode, EvidenceNodeStatus, EvidenceSource


class EvidenceTree:
    """Directed Acyclic Graph (DAG) container for tree-structured working memory."""

    def __init__(self, root_id: str = "root", root_claim: str = "Root Research Goal") -> None:
        self.nodes: dict[str, EvidenceNode] = {}
        self.root_id: str = root_id
        now = datetime.now(UTC).isoformat()
        root_node = EvidenceNode(
            node_id=root_id,
            claim=root_claim,
            bounded_summary=BoundedSummary(
                summary=root_claim,
                key_entities=[],
                key_metrics={},
                estimated_tokens=len(root_claim) // 4,
            ),
            source=EvidenceSource(title="User Research Intent"),
            dependencies=[],
            dependents=[],
            created_at=now,
            updated_at=now,
        )
        self.nodes[root_id] = root_node

    def add_node(self, node: EvidenceNode) -> None:
        """Add an evidence node into the tree, automatically wiring bidirectional dependency links."""
        if node.node_id in self.nodes:
            existing = self.nodes[node.node_id]
            node.dependents = list(set(existing.dependents + node.dependents))
            node.dependencies = list(set(existing.dependencies + node.dependencies))
        self.nodes[node.node_id] = node

        # Ensure dependencies have node registered as a dependent
        for dep_id in node.dependencies:
            if dep_id in self.nodes:
                dep_node = self.nodes[dep_id]
                if node.node_id not in dep_node.dependents:
                    dep_node.dependents.append(node.node_id)

    def get_node(self, node_id: str) -> EvidenceNode | None:
        """Retrieve node by ID."""
        return self.nodes.get(node_id)

    def get_active_nodes(self) -> list[EvidenceNode]:
        """Return all nodes currently active or disputed (eligible for prompt context)."""
        return [
            n for n in self.nodes.values()
            if n.status in (EvidenceNodeStatus.ACTIVE, EvidenceNodeStatus.DISPUTED)
        ]

    def get_downstream_dependents(self, node_id: str) -> list[str]:
        """Collect all downstream nodes recursively dependent on node_id (excluding self)."""
        visited: set[str] = set()
        queue: deque[str] = deque([node_id])
        result: list[str] = []

        while queue:
            curr_id = queue.popleft()
            curr_node = self.nodes.get(curr_id)
            if not curr_node:
                continue
            for dependent_id in curr_node.dependents:
                if dependent_id not in visited:
                    visited.add(dependent_id)
                    result.append(dependent_id)
                    queue.append(dependent_id)

        return result

    def get_upstream_dependencies(self, node_id: str) -> list[str]:
        """Collect all prerequisite nodes upstream on which node_id depends."""
        visited: set[str] = set()
        queue: deque[str] = deque([node_id])
        result: list[str] = []

        while queue:
            curr_id = queue.popleft()
            curr_node = self.nodes.get(curr_id)
            if not curr_node:
                continue
            for dep_id in curr_node.dependencies:
                if dep_id not in visited:
                    visited.add(dep_id)
                    result.append(dep_id)
                    queue.append(dep_id)

        return result

    def project_sub_tree(self, focus_node_ids: list[str]) -> EvidenceTree:
        """Create a projected sub-tree containing only nodes relevant to the focus targets."""
        relevant_ids: set[str] = set(focus_node_ids)
        for nid in focus_node_ids:
            relevant_ids.update(self.get_upstream_dependencies(nid))

        projected = EvidenceTree(root_id=self.root_id, root_claim=self.nodes[self.root_id].claim)
        for nid in sorted(relevant_ids):
            if nid in self.nodes and nid != self.root_id:
                node = self.nodes[nid]
                filtered_deps = [d for d in node.dependencies if d in relevant_ids]
                filtered_dependents = [d for d in node.dependents if d in relevant_ids]
                clone = node.model_copy(
                    update={"dependencies": filtered_deps, "dependents": filtered_dependents}
                )
                projected.add_node(clone)

        return projected

    def format_bounded_slice(self, max_tokens: int = 4000) -> str:
        """Compile an ordered bounded summary slice for orchestrator prompt injection.

        Nodes are sorted stably by creation timestamp to preserve KV prompt cache prefixes.
        """
        active_nodes = [
            n for n in self.nodes.values()
            if n.node_id != self.root_id and n.status in (EvidenceNodeStatus.ACTIVE, EvidenceNodeStatus.DISPUTED)
        ]
        # Sort stably by creation timestamp to maintain identical prefix tokens for KV caching
        active_nodes.sort(key=lambda n: n.created_at)

        lines: list[str] = [
            "### [EVIDENCE WORKING MEMORY (Tree-Structured & Verified)]",
            "The following verified knowledge tree nodes represent current factual consensus:",
        ]

        total_tokens = 0
        for node in active_nodes:
            status_tag = " [DISPUTED]" if node.status == EvidenceNodeStatus.DISPUTED else ""
            source_tag = f" (Source: {node.source.url})" if node.source.url else ""
            metrics_str = (
                f" | Metrics: {', '.join(f'{k}={v}' for k, v in node.bounded_summary.key_metrics.items())}"
                if node.bounded_summary.key_metrics
                else ""
            )
            node_line = (
                f"- [{node.node_id}]{status_tag} {node.bounded_summary.summary}{metrics_str}{source_tag}"
            )
            approx_tokens = len(node_line) // 4
            if total_tokens + approx_tokens > max_tokens:
                lines.append("... [Additional earlier evidence nodes omitted to respect bounded budget]")
                break
            lines.append(node_line)
            total_tokens += approx_tokens

        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        """Serialize tree to a JSON-compatible dictionary."""
        return {
            "root_id": self.root_id,
            "nodes": {nid: node.model_dump() for nid, node in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> EvidenceTree:
        """Deserialize tree from a dictionary."""
        root_id = str(data.get("root_id", "root"))
        nodes_raw = data.get("nodes")
        tree = cls(root_id=root_id)
        if isinstance(nodes_raw, dict):
            tree.nodes.clear()
            for nid, ndict in nodes_raw.items():
                if isinstance(ndict, dict):
                    node = EvidenceNode.model_validate(ndict)
                    tree.nodes[str(nid)] = node
        return tree
