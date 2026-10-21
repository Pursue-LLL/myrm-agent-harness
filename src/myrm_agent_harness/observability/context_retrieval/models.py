"""
[INPUT]
- 无外部重型依赖，基于 Python 标准库 dataclasses, enum, typing

[OUTPUT]
- PruningReason: 剪枝原因枚举 (SCORE_BELOW_THRESHOLD, TOPK_OVERFLOW, SEMANTIC_DEDUP, POLICY_BLOCKED, UNKNOWN)
- RetrievalTreeNode: 结构化下钻决策树节点
- VisitedPathTrace: 单次上下文检索完整决策轨迹快照

[POS]
myrm-agent-harness/src/myrm_agent_harness/observability/context_retrieval/models.py — 上下文检索决策树与剪枝决策数据模型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class PruningReason(str, Enum):
    """上下文检索节点被剪枝丢弃的根本原因枚举。"""

    NONE = "none"
    SCORE_BELOW_THRESHOLD = "score_below_threshold"
    TOPK_OVERFLOW = "topk_overflow"
    SEMANTIC_DEDUP = "semantic_dedup"
    POLICY_BLOCKED = "policy_blocked"
    UNKNOWN = "unknown"


@dataclass
class RetrievalTreeNode:
    """分层目录检索下钻决策树节点。"""

    node_id: str
    name: str
    path: str
    depth: int = 0
    similarity_score: float = 0.0
    pruning_threshold: float = 0.0
    is_pruned: bool = False
    pruning_reason: PruningReason = PruningReason.NONE
    reason_detail: str = ""
    is_hit: bool = False
    metadata: dict[str, str] = field(default_factory=dict)
    children: list[RetrievalTreeNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """序列化为字典结构。"""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "path": self.path,
            "depth": self.depth,
            "similarity_score": round(self.similarity_score, 4),
            "pruning_threshold": round(self.pruning_threshold, 4),
            "is_pruned": self.is_pruned,
            "pruning_reason": self.pruning_reason.value,
            "reason_detail": self.reason_detail,
            "is_hit": self.is_hit,
            "metadata": dict(self.metadata),
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class VisitedPathTrace:
    """单次检索操作的完整决策树轨迹与剪枝汇总快照。"""

    trace_id: str
    query: str
    root_nodes: list[RetrievalTreeNode] = field(default_factory=list)
    total_nodes_visited: int = 0
    pruned_nodes_count: int = 0
    hits_count: int = 0
    duration_ms: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 兼容字典。"""
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "root_nodes": [node.to_dict() for node in self.root_nodes],
            "total_nodes_visited": self.total_nodes_visited,
            "pruned_nodes_count": self.pruned_nodes_count,
            "hits_count": self.hits_count,
            "duration_ms": round(self.duration_ms, 2),
            "created_at": self.created_at,
        }
