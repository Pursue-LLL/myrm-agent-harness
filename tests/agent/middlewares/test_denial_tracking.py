"""Tests for approval middleware helpers — denial tracking with dual thresholds."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.middlewares.approval.helpers import (
    ThresholdBreach,
    is_threshold_breached,
    record_approval,
    record_denial,
    reset_denial_counter,
)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_denial_counter()


class TestRecordDenial:
    def test_first_denial_returns_guidance(self) -> None:
        hint = record_denial("shell_exec")
        assert "Find a safer alternative" in hint
        assert "Do NOT attempt to circumvent" in hint

    def test_second_denial_still_guidance(self) -> None:
        record_denial("shell_exec")
        hint = record_denial("web_fetch")
        assert "Find a safer alternative" in hint
        assert "Auto-mode is being suspended" not in hint

    def test_consecutive_threshold_triggers_escalation(self) -> None:
        for _ in range(2):
            record_denial("shell_exec")
        hint = record_denial("shell_exec")
        assert "3 consecutive denials" in hint
        assert "Auto-mode is being suspended" in hint

    def test_threshold_tracks_across_tools(self) -> None:
        record_denial("tool_a")
        record_denial("tool_b")
        hint = record_denial("tool_c")
        assert "3 consecutive denials" in hint


class TestRecordApproval:
    def test_resets_consecutive_counter(self) -> None:
        record_denial("shell_exec")
        record_denial("shell_exec")
        record_approval()
        hint = record_denial("shell_exec")
        assert "Auto-mode is being suspended" not in hint
        assert "Find a safer alternative" in hint

    def test_does_not_reset_total(self) -> None:
        for _ in range(19):
            record_denial("shell_exec")
            record_approval()

        hint = record_denial("shell_exec")
        assert "20 total denials" in hint
        assert "Auto-mode is being suspended" in hint


class TestIsThresholdBreached:
    def test_none_initially(self) -> None:
        assert is_threshold_breached() == ThresholdBreach.NONE

    def test_consecutive_breach(self) -> None:
        for _ in range(3):
            record_denial("tool")
        assert is_threshold_breached() == ThresholdBreach.CONSECUTIVE

    def test_total_breach(self) -> None:
        for i in range(20):
            record_denial(f"tool_{i}")
            if i < 19:
                record_approval()
        assert is_threshold_breached() == ThresholdBreach.TOTAL

    def test_consecutive_resets_on_approval(self) -> None:
        record_denial("tool")
        record_denial("tool")
        record_approval()
        assert is_threshold_breached() == ThresholdBreach.NONE


class TestResetDenialCounter:
    def test_clears_all_state(self) -> None:
        for _ in range(5):
            record_denial("tool")
        reset_denial_counter()
        assert is_threshold_breached() == ThresholdBreach.NONE

    def test_hint_after_reset_is_guidance(self) -> None:
        for _ in range(5):
            record_denial("tool")
        reset_denial_counter()
        hint = record_denial("tool")
        assert "Find a safer alternative" in hint
        assert "Auto-mode is being suspended" not in hint


class TestTotalThresholdPriority:
    """Total threshold takes priority over consecutive when both are breached."""

    def test_total_takes_priority(self) -> None:
        for _ in range(20):
            record_denial("tool")
        assert is_threshold_breached() == ThresholdBreach.TOTAL
        hint = record_denial("tool")
        assert "total denials" in hint
