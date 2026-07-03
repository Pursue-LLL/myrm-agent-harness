"""Tests for action_capture types."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.toolkits.browser.action_capture.types import (
    ActionStep,
    ActionType,
    CaptureSession,
)


class TestActionType:
    def test_all_types_are_strings(self) -> None:
        for t in ActionType:
            assert isinstance(t.value, str)

    def test_click_value(self) -> None:
        assert ActionType.CLICK.value == "click"

    def test_from_string(self) -> None:
        assert ActionType("navigate") == ActionType.NAVIGATE

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            ActionType("nonexistent")


class TestActionStep:
    def test_immutable(self) -> None:
        step = ActionStep(seq=1, action=ActionType.CLICK, selector="#btn")
        with pytest.raises(AttributeError):
            step.seq = 2  # type: ignore[misc]

    def test_default_values(self) -> None:
        step = ActionStep(seq=1, action=ActionType.TYPE, selector="input")
        assert step.value == ""
        assert step.url == ""
        assert step.is_password is False
        assert step.screenshot_b64 is None

    def test_password_flag(self) -> None:
        step = ActionStep(seq=1, action=ActionType.TYPE, selector="input", is_password=True)
        assert step.is_password is True

    def test_timestamp_auto_set(self) -> None:
        before = time.time()
        step = ActionStep(seq=1, action=ActionType.CLICK, selector="#x")
        after = time.time()
        assert before <= step.timestamp <= after


class TestCaptureSession:
    def test_initial_state(self) -> None:
        session = CaptureSession(session_id="test-123")
        assert session.status == "recording"
        assert session.steps == []
        assert session.next_seq == 1

    def test_add_step(self) -> None:
        session = CaptureSession(session_id="s1")
        step = ActionStep(seq=1, action=ActionType.CLICK, selector="#btn")
        session.add_step(step)
        assert len(session.steps) == 1
        assert session.next_seq == 2

    def test_multiple_steps_sequence(self) -> None:
        session = CaptureSession(session_id="s2")
        for i in range(5):
            session.add_step(ActionStep(seq=i + 1, action=ActionType.CLICK, selector=f"#btn{i}"))
        assert len(session.steps) == 5
        assert session.next_seq == 6
