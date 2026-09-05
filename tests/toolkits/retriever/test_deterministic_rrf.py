"""Unit tests for deterministic RRF fusion with tie-breaking and adaptive normalization."""

from __future__ import annotations

import pytest

from myrm_agent_harness.api import (
    FusedHit,
    RankedList,
    RecallDebug,
    fuse_rrf_deterministic,
)


def test_fuse_rrf_deterministic_consensus_precedence() -> None:
    # 模拟两路召回：FTS 和 Vector
    # doc-A 同时被 FTS 和 Vector 命中（双路共识）
    # doc-B 仅被 FTS 命中第一名
    list1 = RankedList(source="fts", items=["doc-B", "doc-A", "doc-C"], weight=1.0)
    list2 = RankedList(source="vector", items=["doc-A", "doc-D"], weight=1.0)

    fused, debug = fuse_rrf_deterministic(
        [list1, list2],
        key_func=lambda x: x,
        k=60,
        top_k=10,
    )

    # doc-A 理论得分: 1/62 + 1/61 > doc-B: 1/61
    assert fused[0].item == "doc-A"
    assert len(fused[0].hit_by) == 2
    assert fused[0].score > 0.9  # 自适应归一化至高置信度区间

    assert debug.fused_count == 4
    assert len(debug.per_source) == 2


def test_fuse_rrf_deterministic_tie_breaker_alphabetical() -> None:
    # 构造完全同分且命中路数相同的极端平局场景：
    # doc-Y 和 doc-X 分别在两路互换位置 (rank 1 vs rank 2)
    # doc-X: rank 1 (list1) + rank 2 (list2)
    # doc-Y: rank 2 (list1) + rank 1 (list2)
    # 得分和被命中路数均完全一致！
    list1 = RankedList(source="s1", items=["doc-Y", "doc-X"], weight=1.0)
    list2 = RankedList(source="s2", items=["doc-X", "doc-Y"], weight=1.0)

    fused, _ = fuse_rrf_deterministic(
        [list1, list2],
        key_func=lambda x: x,
        k=60,
    )

    # 验证三阶决断：由于分数相同且都是 2 路命中，必须严格按字母序升序决断 ("doc-X" < "doc-Y")
    assert fused[0].item == "doc-X"
    assert fused[1].item == "doc-Y"


def test_fuse_rrf_deterministic_single_source_degradation() -> None:
    # 单路降级场景（例如 Qdrant 故障只有 FTS 返回）
    list1 = RankedList(source="fts", items=["doc-1", "doc-2"], weight=1.0)
    list2 = RankedList(source="vector", items=[], weight=1.0)

    fused, debug = fuse_rrf_deterministic(
        [list1, list2],
        key_func=lambda x: x,
        k=60,
    )

    assert len(fused) == 2
    # 单路降级时，Top-1 仍能自适应归一化至高分，不被 min_score=0.5 误杀
    assert fused[0].score >= 0.8
    assert debug.fused_count == 2
    assert debug.per_source[1].count == 0


def test_fuse_rrf_deterministic_empty_input() -> None:
    fused, debug = fuse_rrf_deterministic([], key_func=lambda x: x)
    assert fused == []
    assert debug.fused_count == 0
