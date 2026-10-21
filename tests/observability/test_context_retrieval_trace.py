"""
[INPUT]
- myrm_agent_harness.observability.context_retrieval::PruningReason, RetrievalTreeNode, VisitedPathTrace, ContextRetrievalTracer

[OUTPUT]
- 上下文检索决策树与剪枝决策跟踪单元测试

[POS]
myrm-agent-harness/tests/observability/test_context_retrieval_trace.py — 检索决策树可观测性单测。
"""

import pytest
from myrm_agent_harness.observability.context_retrieval import (
    PruningReason,
    RetrievalTreeNode,
    VisitedPathTrace,
    ContextRetrievalTracer,
)


def test_retrieval_tree_node_serialization() -> None:
    node = RetrievalTreeNode(
        node_id="root-1",
        name="技术架构文档",
        path="/docs/arch",
        depth=0,
        similarity_score=0.885,
        pruning_threshold=0.650,
        is_pruned=False,
        is_hit=True,
        metadata={"category": "tech"},
    )
    data = node.to_dict()
    assert data["node_id"] == "root-1"
    assert data["name"] == "技术架构文档"
    assert data["similarity_score"] == 0.885
    assert data["is_pruned"] is False
    assert data["is_hit"] is True
    assert data["children"] == []


def test_context_retrieval_tracer_hierarchical_workflow() -> None:
    tracer = ContextRetrievalTracer(trace_id="trace-retrieval-101", query="OpenViking 检索原理")

    # 1. 添加两个根分类
    root1 = tracer.add_root_node(
        node_id="cat-arch",
        name="核心架构分类",
        path="/viking/arch",
        similarity_score=0.82,
        pruning_threshold=0.70,
    )
    root2 = tracer.add_root_node(
        node_id="cat-market",
        name="营销宣传分类",
        path="/viking/marketing",
        similarity_score=0.45,
        pruning_threshold=0.70,
    )

    # 根分类 2 相似度低于阈值，发生剪枝
    pruned_success = tracer.record_pruning(
        node_id="cat-market",
        reason=PruningReason.SCORE_BELOW_THRESHOLD,
        reason_detail="相关度 0.45 低于剪枝阈值 0.70",
    )
    assert pruned_success is True

    # 2. 根分类 1 下钻二级目录
    child1 = tracer.add_child_node(
        parent_id="cat-arch",
        node_id="sub-observe",
        name="可观测性下钻",
        path="/viking/arch/observability",
        similarity_score=0.91,
        pruning_threshold=0.75,
    )
    assert child1 is not None
    assert child1.depth == 1

    # 3. 二级目录下挂载叶子文件
    leaf1 = tracer.add_child_node(
        parent_id="sub-observe",
        node_id="doc-trace",
        name="retrieval_trace.md",
        path="/viking/arch/observability/trace.md",
        similarity_score=0.96,
        pruning_threshold=0.80,
    )
    leaf2 = tracer.add_child_node(
        parent_id="sub-observe",
        node_id="doc-legacy",
        name="legacy_memo.md",
        path="/viking/arch/observability/memo.md",
        similarity_score=0.72,
        pruning_threshold=0.80,
    )
    assert leaf1 is not None
    assert leaf2 is not None

    # 叶子 2 被剪枝，叶子 1 最终命中装配
    tracer.record_pruning(
        node_id="doc-legacy",
        reason=PruningReason.TOPK_OVERFLOW,
        reason_detail="已达到单轮 Top-1 上限",
    )
    tracer.record_hit(node_id="doc-trace")

    # 尝试将已剪枝节点标记为 hit（应被拒绝）
    hit_pruned = tracer.record_hit(node_id="doc-legacy")
    assert hit_pruned is False

    # 4. 生成聚合快照
    trace = tracer.finalize()
    assert trace.trace_id == "trace-retrieval-101"
    assert trace.query == "OpenViking 检索原理"
    assert trace.total_nodes_visited == 5  # cat-arch, cat-market, sub-observe, doc-trace, doc-legacy
    assert trace.pruned_nodes_count == 2   # cat-market, doc-legacy
    assert trace.hits_count == 1          # doc-trace
    assert trace.duration_ms >= 0.0

    trace_dict = trace.to_dict()
    assert len(trace_dict["root_nodes"]) == 2
    assert trace_dict["total_nodes_visited"] == 5
