"""Unit tests for CompactorPreflightFence."""

from myrm_agent_harness.agent.context_management.infra.compactor_guard import (
    CompactorPreflightFence,
)


def test_compactor_preflight_fence() -> None:
    fence = CompactorPreflightFence(safe_watermark_ratio=0.85)

    # Safe
    v_safe = fence.evaluate_safety(
        messages_tokens=50_000,
        loaded_skills_tokens=10_000,
        prompt_overhead=2_000,
        max_context_tokens=100_000,
    )
    assert v_safe.is_safe is True
    assert v_safe.action_recommended == "proceed"

    # Exceed watermark but within physical window
    v_warn = fence.evaluate_safety(
        messages_tokens=75_000,
        loaded_skills_tokens=12_000,
        prompt_overhead=2_000,
        max_context_tokens=100_000,
    )
    assert v_warn.is_safe is False
    assert v_warn.action_recommended == "slice_history"

    # Complete overflow
    v_overflow = fence.evaluate_safety(
        messages_tokens=95_000,
        loaded_skills_tokens=10_000,
        prompt_overhead=2_000,
        max_context_tokens=100_000,
    )
    assert v_overflow.is_safe is False
    assert v_overflow.action_recommended == "emergency_trim"
