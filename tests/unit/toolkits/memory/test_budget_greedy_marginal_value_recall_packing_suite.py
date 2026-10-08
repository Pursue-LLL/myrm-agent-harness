# [POS]: tests.unit.toolkits.memory.test_budget_greedy_marginal_value_recall_packing_suite
# [INPUT]: myrm_agent_harness.toolkits.memory.budget_packing
# [OUTPUT]: TestBudgetGreedyMarginalValueRecallPackingSuite

"""Unit tests for Budget Greedy Marginal Value Recall Packing Suite (Item 122 P2).

Verifies:
1. Marginal value evaluation and diversity penalty on overlapping candidates.
2. Greedy knapsack packing under strict token budget constraints.
3. Greedy backfilling when first-choice candidates exceed remaining budget.
4. Dual-track token accounting (Billed Tokens vs Storage Tokens) accuracy.
5. Orchestration facade support for both knapsack mode and legacy mode.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.budget_packing.estimator import (
    calculate_content_overlap,
    estimate_tokens,
)
from myrm_agent_harness.toolkits.memory.budget_packing.greedy_packer import (
    GreedyMarginalValuePacker,
)
from myrm_agent_harness.toolkits.memory.budget_packing.marginal_value_evaluator import (
    MarginalValueEvaluator,
)
from myrm_agent_harness.toolkits.memory.budget_packing.models import (
    BilledTokenBudget,
    PackingDecisionReason,
    RecallCandidate,
)
from myrm_agent_harness.toolkits.memory.budget_packing.orchestrator import (
    BudgetRecallPackingOrchestrator,
)


def _make_candidate(
    cid: str,
    content: str,
    relevance: float,
    confidence: float = 1.0,
    billed_tokens: int = 50,
    storage_tokens: int = 80,
    tags: tuple[str, ...] = ("memory",),
) -> RecallCandidate:
    return RecallCandidate(
        id=cid,
        content=content,
        relevance_score=relevance,
        confidence_score=confidence,
        billed_tokens=billed_tokens,
        storage_tokens=storage_tokens,
        domain_tags=tags,
    )


class TestBudgetGreedyMarginalValueRecallPackingSuite:
    """Test suite for Item 122 greedy knapsack packing."""

    def test_text_similarity_and_evaluator_first_item(self) -> None:
        """First candidate has zero redundancy and full marginal information gain."""
        evaluator = MarginalValueEvaluator()
        cand = _make_candidate("c1", "用户明确要求代码严禁使用 any 类型注解，必须提供具体类型。", 0.95, billed_tokens=20)

        metrics = evaluator.evaluate_candidate(cand, ())
        assert metrics.base_utility == pytest.approx(0.95, abs=1e-3)
        assert metrics.redundancy_score == 0.0
        assert metrics.marginal_info_gain == 1.0
        assert metrics.marginal_value == pytest.approx(0.95, abs=1e-3)
        assert metrics.marginal_value_density == pytest.approx(0.95 / 20, abs=1e-3)

    def test_diversity_penalty_on_semantic_overlapping_candidates(self) -> None:
        """Second candidate with high overlap receives diversity penalty."""
        evaluator = MarginalValueEvaluator(BilledTokenBudget(diversity_penalty_lambda=0.8))
        first = _make_candidate("c1", "后端架构采用 FastAPI 和 PostgreSQL 数据源。", 0.90)
        second_duplicate = _make_candidate("c2", "后端核心框架采用 FastAPI 搭配 PostgreSQL 数据库。", 0.88)
        third_novel = _make_candidate("c3", "前端界面采用 React 19 和 TailwindCSS 原子样式。", 0.85)

        m_dup = evaluator.evaluate_candidate(second_duplicate, (first,))
        m_novel = evaluator.evaluate_candidate(third_novel, (first,))

        # Overlapping item has significant redundancy score and reduced marginal gain
        assert m_dup.redundancy_score > 0.4
        assert m_dup.marginal_info_gain < 0.7
        assert m_dup.marginal_value < m_dup.base_utility

        # Novel item has near-zero redundancy and maintains full marginal value
        assert m_novel.redundancy_score < 0.15
        assert m_novel.marginal_info_gain > 0.85
        assert m_novel.marginal_value > m_dup.marginal_value

    def test_greedy_knapsack_packs_by_value_density_under_budget(self) -> None:
        """Packer prioritizes candidates with highest marginal value density."""
        packer = GreedyMarginalValuePacker()
        # c1: utility ~0.90, tokens=100 -> density ~0.009
        # c2: utility ~0.80, tokens=20  -> density ~0.040 (higher density)
        # c3: utility ~0.70, tokens=20  -> density ~0.035
        c1 = _make_candidate("c1", "大篇幅系统全生命周期设计说明文档，包含多种冗余背景细节。", 0.90, billed_tokens=100)
        c2 = _make_candidate("c2", "核心准则：模块单个文件不能超过400行。", 0.80, billed_tokens=20)
        c3 = _make_candidate("c3", "核心准则：所有的变更需要全量单元测试绿灯。", 0.70, billed_tokens=20)

        budget = BilledTokenBudget(max_billed_tokens=50, max_items_limit=5)
        result = packer.pack([c1, c2, c3], budget)

        # c2 and c3 have higher density and combined tokens=40 <= 50; c1 cannot fit
        packed_ids = [item.candidate.id for item in result.packed_items]
        assert packed_ids == ["c2", "c3"]
        assert result.accounting.billed_tokens_spent == 40
        assert result.accounting.items_packed_count == 2
        assert result.accounting.items_dropped_count == 1
        assert result.dropped_candidates[0].reason == PackingDecisionReason.BUDGET_EXHAUSTED

    def test_greedy_backfill_fills_capacity_with_smaller_fragments(self) -> None:
        """When top-density item is too large for remaining budget, smaller item backfills."""
        packer = GreedyMarginalValuePacker()
        # Budget: 70 tokens.
        # c1: utility 0.90, tokens 50 -> density 0.018 (Rank 1, fits: 50/70, 20 left)
        # c2_large: utility 0.70, tokens 40 -> density 0.0175 (Rank 2, needs 40 > 20, overflows)
        # c3_small: utility 0.30, tokens 20 -> density 0.015 (Rank 3, needs 20 <= 20, fits via backfill!)
        c1 = _make_candidate("c1", "主要架构模块服务声明与生命周期。", 0.90, billed_tokens=50)
        c2_large = _make_candidate("c2", "较为冗长但相关的安全审计合规全流程细节日志。", 0.70, billed_tokens=40)
        c3_small = _make_candidate("c3", "轻量级环境变量配置规约。", 0.30, billed_tokens=20)

        budget_with_backfill = BilledTokenBudget(
            max_billed_tokens=70,
            allow_greedy_backfill=True,
            max_redundancy_threshold=0.8,
        )
        result = packer.pack([c1, c2_large, c3_small], budget_with_backfill)

        packed_ids = [p.candidate.id for p in result.packed_items]
        assert packed_ids == ["c1", "c3"]
        assert "c2" not in packed_ids
        assert result.accounting.billed_tokens_spent == 70
        assert result.accounting.billed_tokens_remaining == 0
        assert len(result.dropped_candidates) == 1
        assert result.dropped_candidates[0].candidate.id == "c2"
        assert result.dropped_candidates[0].reason == PackingDecisionReason.BUDGET_EXHAUSTED

    def test_dual_track_accounting_and_prompt_block_generation(self) -> None:
        """Dual-track token accounting correctly reflects billed vs storage tokens."""
        orchestrator = BudgetRecallPackingOrchestrator()
        candidates = [
            _make_candidate("c1", "首选架构规范指南。", 0.90, billed_tokens=40, storage_tokens=100),
            _make_candidate("c2", "首选架构规范指南相似重复片段。", 0.85, billed_tokens=40, storage_tokens=90),
            _make_candidate("c3", "全新的日志聚合监控体系。", 0.80, billed_tokens=30, storage_tokens=70),
        ]

        result = orchestrator.pack_candidates(
            candidates,
            budget=BilledTokenBudget(
                max_billed_tokens=80,
                diversity_penalty_lambda=0.9,
                max_redundancy_threshold=0.45,
            ),
            enable_knapsack=True,
        )

        accounting = result.accounting
        assert accounting.total_candidates_examined == 3
        assert accounting.billed_tokens_spent == 70  # c1 (40) + c3 (30)
        assert accounting.storage_tokens_total == 260
        assert accounting.storage_tokens_saved == 90  # c2 was suppressed
        assert accounting.redundant_tokens_filtered == 40
        assert accounting.budget_utilization_pct == pytest.approx(87.5, abs=0.1)

        # Verify XML prompt block structure
        assert '<recalled_memories billed_tokens="70" budget="80" count="2">' in result.composed_prompt_block
        assert '<memory_item id="c1"' in result.composed_prompt_block
        assert '<memory_item id="c3"' in result.composed_prompt_block
        assert "</recalled_memories>" in result.composed_prompt_block

    def test_orchestrator_inspection_and_legacy_mode_fallback(self) -> None:
        """Orchestrator inspects marginal values and provides legacy mode comparisons."""
        orchestrator = BudgetRecallPackingOrchestrator()
        candidates = [
            _make_candidate("c1", "SQLite 嵌入式存储引擎。", 0.90, billed_tokens=30),
            _make_candidate("c2", "Qdrant 向量检索插件。", 0.80, billed_tokens=30),
        ]

        # Test inspection
        inspected = orchestrator.inspect_marginal_evaluation(candidates)
        assert len(inspected) == 2
        assert inspected[0][1].marginal_value > 0
        assert inspected[1][1].marginal_value > 0

        # Test legacy mode passthrough
        legacy_result = orchestrator.pack_candidates(
            candidates,
            budget=BilledTokenBudget(max_billed_tokens=100),
            enable_knapsack=False,
        )
        assert legacy_result.active_mode == "legacy_limit_passthrough"
        assert len(legacy_result.packed_items) == 2

    def test_conservative_bilingual_token_estimation_and_overlap(self) -> None:
        """Verify conservative bilingual token estimation and bigram overlap calculation."""
        # Empty text yields 0 tokens
        assert estimate_tokens("") == 0

        # CJK text conservative ceiling (10 chars * 1.2 = 12 tokens)
        cjk_text = "这是一段测试中文内存文本"
        assert estimate_tokens(cjk_text) >= 10

        # English text conservative ceiling
        en_text = "FastAPI backend architecture with SQLite memory store"
        assert estimate_tokens(en_text) >= 7

        # Mixed text
        mixed_text = "FastAPI 后端架构和 SQLite 嵌入式存储。"
        assert estimate_tokens(mixed_text) >= 8

        # Bigram overlap calculation
        overlap_identical = calculate_content_overlap("完全相同的测试文本", "完全相同的测试文本")
        assert overlap_identical == 1.0

        overlap_partial = calculate_content_overlap("FastAPI 架构服务组件", "FastAPI 数据存储组件")
        assert 0.3 < overlap_partial < 0.9

        overlap_none = calculate_content_overlap("全然不同的一段话", "English only different string")
        assert overlap_none == 0.0

