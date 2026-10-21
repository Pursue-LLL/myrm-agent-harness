"""
[INPUT]:
- myrm_agent_harness.observability.reasoning_semantics::ProviderReasoningNormalizer
- myrm_agent_harness.observability.reasoning_semantics::ReasoningInvariantGuard
- myrm_agent_harness.observability.reasoning_semantics::models

[OUTPUT]:
- Pytest unit tests verifying provider normalization (OpenAI, Anthropic, DeepSeek, vLLM), zero-double-counting invariants, and guard auto-remediation.

[POS]:
tests/observability/test_reasoning_semantics.py — 推理 Token 计费语义契约与重复计数回归守卫单元测试。
"""

import pytest

from myrm_agent_harness.observability.reasoning_semantics import (
    InvariantCheckResult,
    NormalizedTokenUsageSnapshot,
    ProviderReasoningNormalizer,
    ReasoningInclusionPolicy,
    ReasoningInvariantGuard,
)


def test_provider_normalizer_openai_anthropic_deepseek() -> None:
    normalizer = ProviderReasoningNormalizer()

    # 1. 模拟 OpenAI o1 / o3 响应 (completion_tokens 包含 reasoning_tokens)
    openai_raw = {
        "prompt_tokens": 1200,
        "completion_tokens": 3500,
        "completion_tokens_details": {
            "reasoning_tokens": 2000,
        },
        "total_tokens": 4700,
    }
    s_openai = normalizer.normalize("openai/o3-mini", openai_raw)
    assert s_openai.prompt_tokens == 1200
    assert s_openai.completion_tokens == 3500
    assert s_openai.reasoning_tokens == 2000
    assert s_openai.visible_content_tokens == 1500  # 3500 - 2000
    assert s_openai.total_tokens == 4700  # 1200 + 3500 (严格零重复相加)
    assert s_openai.is_zero_double_counted is True
    assert s_openai.policy_applied == ReasoningInclusionPolicy.INCLUDED_IN_COMPLETION

    # 2. 模拟 Anthropic Claude 3.7 Sonnet Thinking (thinking_tokens 计入 output)
    anthropic_raw = {
        "input_tokens": 2000,
        "output_tokens": 4000,
        "thinking_tokens": 2500,
    }
    s_anthropic = normalizer.normalize("anthropic/claude-3-7-sonnet", anthropic_raw)
    assert s_anthropic.prompt_tokens == 2000
    assert s_anthropic.completion_tokens == 4000
    assert s_anthropic.reasoning_tokens == 2500
    assert s_anthropic.visible_content_tokens == 1500
    assert s_anthropic.total_tokens == 6000  # 2000 + 4000

    # 3. 模拟 DeepSeek-R1 (reasoning_tokens)
    deepseek_raw = {
        "prompt_tokens": 800,
        "completion_tokens": 2400,
        "reasoning_tokens": 1800,
    }
    s_deepseek = normalizer.normalize("deepseek/deepseek-r1", deepseek_raw)
    assert s_deepseek.prompt_tokens == 800
    assert s_deepseek.completion_tokens == 2400
    assert s_deepseek.reasoning_tokens == 1800
    assert s_deepseek.visible_content_tokens == 600
    assert s_deepseek.total_tokens == 3200


def test_provider_normalizer_standalone_gateway() -> None:
    normalizer = ProviderReasoningNormalizer()

    # 模拟某些自建 vLLM 中转网关 (completion_tokens 仅代表净输出，需显式合并)
    vllm_raw = {
        "prompt_tokens": 1000,
        "completion_tokens": 800,  # 仅 visible
        "reasoning_tokens": 1500,  # standalone
    }
    s_vllm = normalizer.normalize("vllm_standalone_gateway", vllm_raw)
    assert s_vllm.prompt_tokens == 1000
    assert s_vllm.reasoning_tokens == 1500
    assert s_vllm.visible_content_tokens == 800
    assert s_vllm.completion_tokens == 2300  # 800 + 1500
    assert s_vllm.total_tokens == 3300  # 1000 + 2300
    assert s_vllm.policy_applied == ReasoningInclusionPolicy.STANDALONE_OUTPUT


def test_invariant_guard_detects_and_heals_double_counting() -> None:
    normalizer = ProviderReasoningNormalizer()
    guard = ReasoningInvariantGuard()

    # 正常快照
    valid_raw = {
        "prompt_tokens": 1000,
        "completion_tokens": 3000,
        "reasoning_tokens": 1200,
    }
    valid_snap = normalizer.normalize("openai/gpt-4o", valid_raw)

    # 1. 验证完全合规的不变量
    check1 = guard.verify_and_guard(valid_snap)
    assert check1.is_valid is True
    assert check1.violation_type is None
    assert check1.diagnostic_warning is None

    # 2. 模拟上游框架把 total 误算为 prompt + completion + reasoning (1000 + 3000 + 1200 = 5200)
    flawed_double_total = 1000 + 3000 + 1200
    check2 = guard.verify_and_guard(valid_snap, raw_reported_total=flawed_double_total)
    assert check2.is_valid is False
    assert check2.violation_type == "DOUBLE_COUNTING_TOTAL"
    assert "检测到严重重复计数漏洞" in str(check2.diagnostic_warning)

    # 3. 模拟异常数据：reasoning_tokens 超过 completion_tokens，触发自动修正
    overflow_snap = NormalizedTokenUsageSnapshot(
        prompt_tokens=500,
        completion_tokens=1000,
        reasoning_tokens=1500,  # 超过 1000
        visible_content_tokens=0,
        total_tokens=1500,
        cost_usd=0.01,
        is_zero_double_counted=True,
        raw_provider="test-provider",
        policy_applied=ReasoningInclusionPolicy.INCLUDED_IN_COMPLETION,
        normalized_at="2026-10-12T00:00:00Z",
    )
    check3 = guard.verify_and_guard(overflow_snap)
    assert check3.is_valid is False
    assert check3.violation_type == "REASONING_EXCEEDS_COMPLETION"
    assert check3.corrected_snapshot is not None
    # 纠偏后 completion 提升至 1500，total 纠偏为 2000
    assert check3.corrected_snapshot.completion_tokens == 1500
    assert check3.corrected_snapshot.total_tokens == 2000
