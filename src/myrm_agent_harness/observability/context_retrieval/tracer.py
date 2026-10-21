"""
[INPUT]
- .models::PruningReason, RetrievalTreeNode, VisitedPathTrace (POS: 决策树模型)

[OUTPUT]
- ContextRetrievalTracer: 上下文检索决策树与剪枝决策跟踪器

[POS]
myrm-agent-harness/src/myrm_agent_harness/observability/context_retrieval/tracer.py — 检索决策树下钻与剪枝留痕跟踪器。
"""

from __future__ import annotations

import time

from .models import PruningReason, RetrievalTreeNode, VisitedPathTrace


class ContextRetrievalTracer:
    """上下文检索过程白盒化跟踪器。

    支持对目录递归下钻、相关度打分、动态阈值剪枝以及叶子节点命中进行结构化追踪。
    """

    def __init__(self, trace_id: str, query: str) -> None:
        self.trace_id = trace_id
        self.query = query
        self.start_time: float = time.perf_counter()
        self._roots: list[RetrievalTreeNode] = []
        self._node_registry: dict[str, RetrievalTreeNode] = {}
        self._total_visited: int = 0
        self._pruned_count: int = 0
        self._hits_count: int = 0

    def add_root_node(
        self,
        node_id: str,
        name: str,
        path: str,
        similarity_score: float,
        pruning_threshold: float,
        metadata: dict[str, str] | None = None,
    ) -> RetrievalTreeNode:
        """添加顶层根分类/根目录节点。"""
        node = RetrievalTreeNode(
            node_id=node_id,
            name=name,
            path=path,
            depth=0,
            similarity_score=similarity_score,
            pruning_threshold=pruning_threshold,
            metadata=dict(metadata or {}),
        )
        self._roots.append(node)
        self._node_registry[node_id] = node
        self._total_visited += 1
        return node

    def add_child_node(
        self,
        parent_id: str,
        node_id: str,
        name: str,
        path: str,
        similarity_score: float,
        pruning_threshold: float,
        metadata: dict[str, str] | None = None,
    ) -> RetrievalTreeNode | None:
        """向指定父节点挂载子节点。"""
        parent = self._node_registry.get(parent_id)
        if not parent:
            return None

        child = RetrievalTreeNode(
            node_id=node_id,
            name=name,
            path=path,
            depth=parent.depth + 1,
            similarity_score=similarity_score,
            pruning_threshold=pruning_threshold,
            metadata=dict(metadata or {}),
        )
        parent.children.append(child)
        self._node_registry[node_id] = child
        self._total_visited += 1
        return child

    def record_pruning(
        self,
        node_id: str,
        reason: PruningReason,
        reason_detail: str = "",
    ) -> bool:
        """记录某个节点被剪枝丢弃的决策。"""
        node = self._node_registry.get(node_id)
        if not node:
            return False

        if not node.is_pruned:
            node.is_pruned = True
            node.pruning_reason = reason
            node.reason_detail = reason_detail
            self._pruned_count += 1
        return True

    def record_hit(self, node_id: str) -> bool:
        """记录某个叶子节点被最终选中并装配进 Context。"""
        node = self._node_registry.get(node_id)
        if not node or node.is_pruned:
            return False

        if not node.is_hit:
            node.is_hit = True
            self._hits_count += 1
        return True

    def finalize(self) -> VisitedPathTrace:
        """结束本次检索追踪并返回只读聚合快照。"""
        duration_ms = (time.perf_counter() - self.start_time) * 1000.0
        return VisitedPathTrace(
            trace_id=self.trace_id,
            query=self.query,
            root_nodes=list(self._roots),
            total_nodes_visited=self._total_visited,
            pruned_nodes_count=self._pruned_count,
            hits_count=self._hits_count,
            duration_ms=duration_ms,
        )
