"""Tests for OverflowCompactionOnePerInputGuard and is_recoverable_length classifier."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.overflow_compaction_guard import (
    OverflowClassification,
    OverflowCompactionExhaustedGiveUpError,
    OverflowCompactionOnePerInputGuard,
    classify_response_overflow,
    is_recoverable_length,
)


def test_is_recoverable_length_semantics() -> None:
    """Verify is_recoverable_length accurately separates genuine cap from context truncation."""
    # 1. Normal stop reasons are never recoverable length
    assert is_recoverable_length("stop", output_tokens=500, desired_max_output=4096) is False
    assert is_recoverable_length("tool_calls", output_tokens=300, desired_max_output=4096) is False

    # 2. Genuine output cap: model fully utilized the requested token budget
    assert is_recoverable_length("length", output_tokens=4096, desired_max_output=4096) is False
    assert is_recoverable_length("max_tokens", output_tokens=4100, desired_max_output=4096) is False

    # 3. Recoverable length: model stopped below the intended output limit due to context pressure
    assert is_recoverable_length("length", output_tokens=16, desired_max_output=4096) is True
    assert is_recoverable_length("max_tokens", output_tokens=0, desired_max_output=4096) is True
    assert is_recoverable_length("length", output_tokens=2048, desired_max_output=8192) is True


def test_classify_response_overflow_variants() -> None:
    """Verify response classification across errors, output limits, and normal stops."""
    # 1. Explicit provider context length error
    err_cls = classify_response_overflow(
        stop_reason=None,
        output_tokens=0,
        desired_max_output=4096,
        is_explicit_error=True,
        error_message="InvalidRequestError: maximum context length exceeded",
    )
    assert err_cls == OverflowClassification.RECOVERABLE_OVERFLOW

    # 2. Genuine output limit reached
    cap_cls = classify_response_overflow(
        stop_reason="length",
        output_tokens=2048,
        desired_max_output=2048,
    )
    assert cap_cls == OverflowClassification.GENUINE_OUTPUT_CAP

    # 3. Truncated output under intended cap
    rec_cls = classify_response_overflow(
        stop_reason="length",
        output_tokens=256,
        desired_max_output=4096,
    )
    assert rec_cls == OverflowClassification.RECOVERABLE_OVERFLOW

    # 4. Normal completion
    norm_cls = classify_response_overflow(
        stop_reason="stop",
        output_tokens=150,
        desired_max_output=4096,
    )
    assert norm_cls == OverflowClassification.NORMAL


def test_one_recovery_per_input_bounds_compaction_loop() -> None:
    """Verify exactly one overflow compaction is allowed per user input, second triggers give-up."""
    guard = OverflowCompactionOnePerInputGuard(session_id="session-404")
    guard.on_conversational_input_consumed("user-msg-01")

    # First recoverable overflow -> permitted
    decision1 = guard.evaluate_recovery(OverflowClassification.RECOVERABLE_OVERFLOW)
    assert decision1.should_compact is True
    assert decision1.give_up is False
    assert decision1.attempt_count == 1
    assert guard.overflow_compaction_count == 1

    # Second recoverable overflow inside the same input window -> give up!
    decision2 = guard.evaluate_recovery(OverflowClassification.RECOVERABLE_OVERFLOW)
    assert decision2.should_compact is False
    assert decision2.give_up is True
    assert decision2.attempt_count == 2
    assert "give-up error triggered" in decision2.reason

    # check_and_enforce raises explicit give-up exception
    with pytest.raises(OverflowCompactionExhaustedGiveUpError) as exc_info:
        guard.check_and_enforce(OverflowClassification.RECOVERABLE_OVERFLOW)

    assert exc_info.value.session_id == "session-404"
    assert exc_info.value.input_id == "user-msg-01"


def test_new_conversational_input_resets_guard_budget() -> None:
    """Verify consuming a fresh conversational input (prompt, steer, followUp) resets the counter."""
    guard = OverflowCompactionOnePerInputGuard(session_id="session-404")
    guard.on_conversational_input_consumed("prompt-turn-1")

    # Exhaust compaction budget for turn 1
    assert guard.check_and_enforce(OverflowClassification.RECOVERABLE_OVERFLOW) is True
    with pytest.raises(OverflowCompactionExhaustedGiveUpError):
        guard.check_and_enforce(OverflowClassification.RECOVERABLE_OVERFLOW)

    # User injects new steering command or followUp -> fresh conversational input
    guard.on_conversational_input_consumed("steer-turn-2")
    assert guard.current_input_id == "steer-turn-2"
    assert guard.overflow_compaction_count == 0

    # Compaction is permitted again for the new input action
    assert guard.check_and_enforce(OverflowClassification.RECOVERABLE_OVERFLOW) is True
    assert guard.overflow_compaction_count == 1

    # Normal responses do not trigger compaction or consume budget
    assert guard.check_and_enforce(OverflowClassification.NORMAL) is False
