"""
[INPUT]:
- myrm_agent_harness.observability.turn_usage::NormalizedUsage, TurnUsageTracker

[OUTPUT]:
- Pytest verification for dual count operations (summed_with vs merged_with), tracker lifecycle, and shape rewriting.

[POS]:
tests/observability/test_turn_usage.py — 回合级 Billed Usage 双计数核心单元测试。
"""

import pytest

from myrm_agent_harness.observability.turn_usage import (
    NormalizedUsage,
    TurnUsageTracker,
)


def test_normalized_usage_summed_vs_merged_dual_count() -> None:
    # 第一轮：冷启动生成缓存
    round_1 = NormalizedUsage(
        input_tokens=1000,
        output_tokens=200,
        cache_read=0,
        cache_write=1000,
    )
    assert round_1.has_cache_signal is True

    # 第二轮：内部重试/工具循环，命中部分缓存
    round_2 = NormalizedUsage(
        input_tokens=200,
        output_tokens=150,
        cache_read=800,
        cache_write=200,
    )

    # 第三轮：最终收敛，完全命中稳定前缀缓存
    round_3 = NormalizedUsage(
        input_tokens=50,
        output_tokens=300,
        cache_read=1000,
        cache_write=0,
    )

    # 1. 真实账单累加：summed_with (The Bill)
    billed = round_1.summed_with(round_2).summed_with(round_3)
    assert billed.input_tokens == 1000 + 200 + 50
    assert billed.output_tokens == 200 + 150 + 300
    assert billed.cache_read == 0 + 800 + 1000  # 1800 真实向供应商结算的缓存读
    assert billed.cache_write == 1000 + 200 + 0  # 1200 真实写入

    # 2. 冻结决策状态：merged_with (The Freeze)
    # 保持最新携带信号的 round_3 缓存状态，不虚假叠加
    freeze = round_1.merged_with(round_2).merged_with(round_3)
    assert freeze.input_tokens == 1000 + 200 + 50
    assert freeze.output_tokens == 200 + 150 + 300
    assert freeze.cache_read == 1000  # 严格等于 round_3 的当前有效缓存，未被虚增至 1800！
    assert freeze.cache_write == 0  # round_3 的最新缓存写入状态


def test_turn_usage_tracker_lifecycle_and_divergence() -> None:
    tracker = TurnUsageTracker()
    session_id = "sess_dual_001"
    turn_id = "turn_001"

    # 记录 Round 1
    tracker.record_round(
        session_id=session_id,
        turn_id=turn_id,
        usage=NormalizedUsage(
            input_tokens=800,
            output_tokens=100,
            cache_read=200,
            cache_write=600,
        ),
    )

    # 记录 Round 2 (重试或再驱动)
    summary = tracker.record_round(
        session_id=session_id,
        turn_id=turn_id,
        usage=NormalizedUsage(
            input_tokens=100,
            output_tokens=120,
            cache_read=800,
            cache_write=0,
        ),
    )

    assert summary.session_id == session_id
    assert summary.turn_id == turn_id
    assert summary.rounds_count == 2
    # Billed 绝对累加
    assert summary.billed.input_tokens == 900
    assert summary.billed.output_tokens == 220
    assert summary.billed.cache_read == 1000
    assert summary.billed.cache_write == 600

    # Freeze 仅保留最新缓存状态
    assert summary.freeze_usage.cache_read == 800
    assert summary.freeze_usage.cache_write == 0

    # 差异量 = billed_cache (1600) - freeze_cache (800) = 800
    assert summary.cache_divergence_tokens == 800


def test_write_in_shape_openai_and_anthropic() -> None:
    tracker = TurnUsageTracker()
    billed = NormalizedUsage(
        input_tokens=1250,
        output_tokens=320,
        cache_read=900,
        cache_write=150,
    )

    # 1. 回写 OpenAI 形状
    openai_existing = {
        "prompt_tokens": 500,
        "completion_tokens": 100,
        "total_tokens": 600,
        "prompt_tokens_details": {"cached_tokens": 200},
    }
    openai_rewritten = tracker.write_in_shape(openai_existing, billed)
    assert openai_rewritten["prompt_tokens"] == 1250
    assert openai_rewritten["completion_tokens"] == 320
    assert openai_rewritten["total_tokens"] == 1570
    assert openai_rewritten["prompt_tokens_details"]["cached_tokens"] == 900

    # 2. 回写 Anthropic 形状
    anthropic_existing = {
        "input_tokens": 500,
        "output_tokens": 100,
    }
    anthropic_rewritten = tracker.write_in_shape(anthropic_existing, billed)
    assert anthropic_rewritten["input_tokens"] == 1250
    assert anthropic_rewritten["output_tokens"] == 320
    assert anthropic_rewritten["cache_read_input_tokens"] == 900
    assert anthropic_rewritten["cache_creation_input_tokens"] == 150
