"""Unit tests for Token Burn Rate Governor and Runaway Consumption Shield (Item 220).

[INPUT]
- TokenBurnRateGovernorEngine, TokenGovernorConfig, TokenUsageRecord, BurnRateZone, ToolLeanMode.
- Simulated token consumption sequences, tool surfaces, and 429 response scenarios.

[OUTPUT]
- Deterministic verification of rolling window burn velocity tracking, zone classification,
- lean tool dynamic pruning, adaptive exponential 429 backoff, and model fallback diversion.

[POS]
- Verifies prevention of runaway token exhaustion and frequent 429 rate limit outages.
"""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.context_management.token_governor import (
    BurnRateTelemetry,
    BurnRateZone,
    LeanToolPruningDecision,
    RateLimitBackoffDecision,
    TokenBurnRateGovernorEngine,
    TokenGovernorConfig,
    TokenUsageRecord,
    ToolLeanMode,
)


def test_record_usage_and_sliding_window_telemetry() -> None:
    """Verifies token recording, rolling window rate computation, and zone transitions."""
    config = TokenGovernorConfig(
        rolling_window_seconds=60,
        yellow_spike_tpm=20000,
        orange_throttle_tpm=50000,
        red_exhaustion_tpm=100000,
    )
    engine = TokenBurnRateGovernorEngine(config=config)

    now = time.time()

    # Step 1: Low usage -> NORMAL_GREEN
    t1 = engine.record_usage(
        "sess_burn_1",
        TokenUsageRecord(
            prompt_tokens=500,
            completion_tokens=100,
            total_tokens=600,
            model_name="gpt-4o",
            timestamp=now,
        ),
    )
    assert t1.session_id == "sess_burn_1"
    assert t1.sample_count == 1
    assert t1.total_tokens_in_window == 600
    assert t1.zone == BurnRateZone.NORMAL_GREEN
    assert "sustainable" in t1.recommended_action

    # Step 2: Sudden consumption burst -> SPIKE_YELLOW / THROTTLE_ORANGE
    t2 = engine.record_usage(
        "sess_burn_1",
        TokenUsageRecord(
            prompt_tokens=25000,
            completion_tokens=5000,
            total_tokens=30000,
            model_name="gpt-4o",
            timestamp=now + 5.0,
        ),
    )
    assert t2.total_tokens_in_window == 30600
    assert t2.burn_rate_per_minute > 20000
    assert t2.zone in (BurnRateZone.SPIKE_YELLOW, BurnRateZone.THROTTLE_ORANGE, BurnRateZone.EXHAUSTION_RED)

    # Step 3: Extreme runaway burn -> EXHAUSTION_RED
    t3 = engine.record_usage(
        "sess_burn_1",
        TokenUsageRecord(
            prompt_tokens=80000,
            completion_tokens=10000,
            total_tokens=90000,
            model_name="gpt-4o",
            timestamp=now + 10.0,
        ),
    )
    assert t3.zone == BurnRateZone.EXHAUSTION_RED
    assert "Critical token exhaustion" in t3.recommended_action


def test_lean_tool_pruning_decision() -> None:
    """Verifies JIT tool pruning across normal, simple-chat, and throttled conditions."""
    engine = TokenBurnRateGovernorEngine()

    all_tools = [
        "ask_question",
        "read_file",
        "run_command",
        "browser_navigate",
        "generate_image",
        "edit_code",
    ]

    # Scenario A: Minimal tool surface (<= 2 tools) retains full surface
    minimal_decision = engine.resolve_lean_tool_pruning(
        all_tools=["read_file", "write_file"],
        conversation_intent="read something",
    )
    assert minimal_decision.mode == ToolLeanMode.FULL_SURFACE
    assert len(minimal_decision.active_tool_names) == 2
    assert minimal_decision.noise_reduction_ratio == 0.0

    # Scenario B: Casual chat/explain intent -> MINIMAL_CONVERSATIONAL
    chat_decision = engine.resolve_lean_tool_pruning(
        all_tools=all_tools,
        conversation_intent="你好，简单解释一下快速排序的原理",
        active_zone=BurnRateZone.NORMAL_GREEN,
    )
    assert chat_decision.mode == ToolLeanMode.MINIMAL_CONVERSATIONAL
    assert "ask_question" in chat_decision.active_tool_names or "read_file" in chat_decision.active_tool_names
    assert "browser_navigate" in chat_decision.pruned_tool_names
    assert "generate_image" in chat_decision.pruned_tool_names
    assert chat_decision.noise_reduction_ratio > 0.5

    # Scenario C: Throttle Orange with execution intent -> LEAN_PRUNED keeping execution tools
    exec_decision = engine.resolve_lean_tool_pruning(
        all_tools=all_tools,
        conversation_intent="run unit tests with pytest command",
        active_zone=BurnRateZone.THROTTLE_ORANGE,
    )
    assert exec_decision.mode == ToolLeanMode.LEAN_PRUNED
    assert "run_command" in exec_decision.active_tool_names
    assert "browser_navigate" in exec_decision.pruned_tool_names
    assert "generate_image" in exec_decision.pruned_tool_names
    assert exec_decision.noise_reduction_ratio >= 0.5

    # Scenario D: Normal green with generic tasks -> FULL_SURFACE
    normal_decision = engine.resolve_lean_tool_pruning(
        all_tools=all_tools,
        conversation_intent="write a comprehensive web app",
        active_zone=BurnRateZone.NORMAL_GREEN,
    )
    assert normal_decision.mode == ToolLeanMode.FULL_SURFACE
    assert len(normal_decision.active_tool_names) == len(all_tools)
    assert normal_decision.noise_reduction_ratio == 0.0


def test_handle_provider_429_backoff_and_fallback() -> None:
    """Verifies Retry-After parsing, exponential backoff progression, and fallback recommendation."""
    config = TokenGovernorConfig(
        default_backoff_base_seconds=2.0,
        max_backoff_seconds=30.0,
        max_retry_attempts=3,
    )
    engine = TokenBurnRateGovernorEngine(config=config)

    # 1. Explicit Retry-After header
    decision_explicit = engine.handle_provider_429_backoff(
        retry_after_header="7.5",
        attempt_index=1,
    )
    assert decision_explicit.should_retry is True
    assert decision_explicit.backoff_seconds == 7.5
    assert decision_explicit.suggest_model_fallback is False

    # 2. Exponential backoff progression
    d_att1 = engine.handle_provider_429_backoff(attempt_index=1)
    assert d_att1.backoff_seconds == 2.0  # 2 * 2^0

    d_att2 = engine.handle_provider_429_backoff(
        attempt_index=2,
        fallback_candidates=["gemini-2.5-flash", "claude-3-5-haiku"],
    )
    assert d_att2.backoff_seconds == 4.0  # 2 * 2^1
    # Attempt 2 with candidates should suggest model fallback
    assert d_att2.suggest_model_fallback is True
    assert d_att2.fallback_model_candidate == "gemini-2.5-flash"
    assert "Suggesting diversion to fallback model" in d_att2.reason

    # 3. Exceeded max retry attempts
    d_exhausted = engine.handle_provider_429_backoff(
        attempt_index=4,  # > max_retry_attempts (3)
        fallback_candidates=["gemini-2.5-flash"],
    )
    assert d_exhausted.should_retry is False
    assert "Exceeded max retry attempts" in d_exhausted.reason


def test_session_summary_and_clear() -> None:
    """Verifies cumulative session token diagnostics and memory teardown."""
    engine = TokenBurnRateGovernorEngine()

    engine.record_usage(
        "sess_diag",
        TokenUsageRecord(prompt_tokens=1000, completion_tokens=200, total_tokens=1200),
    )
    engine.record_usage(
        "sess_diag",
        TokenUsageRecord(prompt_tokens=2000, completion_tokens=300, total_tokens=2300),
    )

    summary = engine.get_session_summary("sess_diag")
    assert summary["record_count"] == 2
    assert summary["total_prompt_tokens"] == 3000
    assert summary["total_completion_tokens"] == 500
    assert summary["cumulative_tokens"] == 3500

    # Clear session
    engine.clear_session("sess_diag")
    summary_after = engine.get_session_summary("sess_diag")
    assert summary_after["record_count"] == 0
    assert summary_after["cumulative_tokens"] == 0
