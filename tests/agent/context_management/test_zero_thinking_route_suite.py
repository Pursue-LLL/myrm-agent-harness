"""Unit tests for Zero Thinking Budget Direct Route and Cost Decoupling Suite.

Verifies cross-vendor thinking parameter normalization (Anthropic, DeepSeek, OpenAI),
deterministic mechanical task detection, and financial/latency decoupling metrics.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    DeterministicTaskDetection,
    DeterministicTaskDetector,
    ModelProviderKind,
    ProviderThinkingPayload,
    ThinkingBudgetMode,
    ThinkingParameterNormalizer,
    ZeroThinkingBudgetDirectRouteSuite,
    ZeroThinkingSavingsRecord,
)


def test_thinking_parameter_normalizer_cross_provider() -> None:
    """Verify vendor-specific parameter mapping across Anthropic, DeepSeek, and OpenAI."""
    normalizer = ThinkingParameterNormalizer()

    # 1. Anthropic: zero_direct must translate to thinking type disabled
    res_ant_zero = normalizer.normalize("claude-3-7-sonnet", mode=ThinkingBudgetMode.ZERO_DIRECT)
    assert res_ant_zero.provider == ModelProviderKind.ANTHROPIC
    assert res_ant_zero.is_thinking_disabled is True
    assert res_ant_zero.extra_body_params == {"thinking": {"type": "disabled"}}
    assert res_ant_zero.budget_tokens == 0

    # Anthropic: medium budget
    res_ant_med = normalizer.normalize("claude-3-7-sonnet", mode=ThinkingBudgetMode.MEDIUM)
    assert res_ant_med.is_thinking_disabled is False
    assert res_ant_med.extra_body_params == {"thinking": {"type": "enabled", "budget_tokens": 4096}}

    # 2. DeepSeek: zero_direct routes reasoner to fast-lane chat model
    res_ds_zero = normalizer.normalize("deepseek-reasoner", mode=ThinkingBudgetMode.ZERO_DIRECT)
    assert res_ds_zero.provider == ModelProviderKind.DEEPSEEK
    assert res_ds_zero.routed_model_override == "deepseek-chat"
    assert res_ds_zero.is_thinking_disabled is True

    # 3. OpenAI: zero_direct switches to gpt-4o or low reasoning effort
    res_oai_zero = normalizer.normalize("o3-mini", mode=ThinkingBudgetMode.ZERO_DIRECT)
    assert res_oai_zero.provider == ModelProviderKind.OPENAI
    assert res_oai_zero.routed_model_override == "gpt-4o"
    assert res_oai_zero.is_thinking_disabled is True

    # OpenAI: low effort
    res_oai_low = normalizer.normalize("o3-mini", mode=ThinkingBudgetMode.LOW)
    assert res_oai_low.extra_body_params == {"reasoning_effort": "low"}


def test_deterministic_task_detector() -> None:
    """Verify heuristic classification of deterministic mechanical prompts."""
    detector = DeterministicTaskDetector()

    # 1. Format conversion
    det1 = detector.detect("Convert this list to json schema please.")
    assert det1.is_deterministic is True
    assert det1.suggested_mode == ThinkingBudgetMode.ZERO_DIRECT
    assert det1.confidence >= 0.90

    # 2. Translation
    det2 = detector.detect("Translate this string into Japanese.")
    assert det2.is_deterministic is True
    assert det2.detected_pattern == "translation"

    # 3. Explicit fast-lane instruction
    det3 = detector.detect("极速直出，无需深度思考，快速回答")
    assert det3.is_deterministic is True
    assert det3.detected_pattern == "explicit_fast_path"

    # 4. Complex architectural reasoning task must NOT be flagged
    det4 = detector.detect("Design a distributed Paxos consensus ledger with Byzantine fault tolerance.")
    assert det4.is_deterministic is False
    assert det4.suggested_mode == ThinkingBudgetMode.AUTO


def test_zero_thinking_route_suite_facade_and_savings() -> None:
    """Verify master suite orchestration, wire payload routing, and savings telemetry."""
    suite = ZeroThinkingBudgetDirectRouteSuite(
        baseline_thinking_tokens=3000,
        output_token_rate_per_million_usd=15.0,
    )

    # 1. Automatic routing on deterministic prompt
    prompt = "Format this table as markdown and deduplicate lines."
    payload, detection = suite.route_call(
        model_id="claude-3-7-sonnet",
        prompt=prompt,
    )
    assert detection.is_deterministic is True
    assert payload.is_thinking_disabled is True
    assert payload.extra_body_params == {"thinking": {"type": "disabled"}}

    # 2. Record turn telemetry
    rec = suite.record_turn_savings(
        task_description="Format table as markdown",
        mode=ThinkingBudgetMode.ZERO_DIRECT,
        actual_thinking_tokens=0,
    )
    assert rec.avoided_baseline_thinking_tokens == 3000
    assert rec.estimated_cost_saved_usd > 0.04
    assert rec.estimated_ttft_saved_ms >= 3000.0

    # 3. Check cumulative telemetry metrics
    metrics = suite.get_aggregate_savings()
    assert metrics["total_turns_analyzed"] == 1
    assert metrics["zero_direct_fast_lane_turns"] == 1
    assert metrics["total_thinking_tokens_avoided"] == 3000
    assert metrics["average_ttft_saved_ms"] >= 3000.0
