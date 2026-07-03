"""Tests for action_capture serializer."""

from __future__ import annotations

from myrm_agent_harness.toolkits.browser.action_capture.serializer import (
    serialize_session,
    serialize_step,
    step_to_natural_language,
    steps_to_natural_language,
)
from myrm_agent_harness.toolkits.browser.action_capture.types import (
    ActionStep,
    ActionType,
    CaptureSession,
)


def _make_step(
    seq: int = 1,
    action: ActionType = ActionType.CLICK,
    selector: str = "#btn",
    value: str = "",
    element_text: str = "Submit",
    element_role: str = "button",
    is_password: bool = False,
    screenshot_b64: str | None = None,
) -> ActionStep:
    return ActionStep(
        seq=seq,
        action=action,
        selector=selector,
        value=value,
        element_text=element_text,
        element_role=element_role,
        is_password=is_password,
        screenshot_b64=screenshot_b64,
        url="https://example.com",
        title="Test Page",
        timestamp=1000.0,
    )


class TestSerializeStep:
    def test_basic_fields(self) -> None:
        step = _make_step()
        d = serialize_step(step)
        assert d["seq"] == 1
        assert d["action"] == "click"
        assert d["selector"] == "#btn"
        assert "screenshot_b64" not in d

    def test_includes_screenshot_when_requested(self) -> None:
        step = _make_step(screenshot_b64="abc123")
        d = serialize_step(step, include_screenshot=True)
        assert d["screenshot_b64"] == "abc123"

    def test_excludes_screenshot_by_default(self) -> None:
        step = _make_step(screenshot_b64="abc123")
        d = serialize_step(step)
        assert "screenshot_b64" not in d

    def test_password_field(self) -> None:
        step = _make_step(is_password=True)
        d = serialize_step(step)
        assert d["is_password"] is True


class TestSerializeSession:
    def test_empty_session(self) -> None:
        session = CaptureSession(session_id="s1", start_url="https://example.com")
        d = serialize_session(session)
        assert d["session_id"] == "s1"
        assert d["step_count"] == 0
        assert d["steps"] == []

    def test_session_with_steps(self) -> None:
        session = CaptureSession(session_id="s2")
        session.add_step(_make_step(seq=1))
        session.add_step(_make_step(seq=2, action=ActionType.TYPE, value="hello"))
        d = serialize_session(session)
        assert d["step_count"] == 2
        assert len(d["steps"]) == 2  # type: ignore[arg-type]


class TestNaturalLanguage:
    def test_click(self) -> None:
        step = _make_step(action=ActionType.CLICK, element_text="Submit", element_role="button")
        nl = step_to_natural_language(step)
        assert "Submit" in nl
        assert "button" in nl

    def test_type(self) -> None:
        step = _make_step(action=ActionType.TYPE, value="hello", element_role="textbox")
        nl = step_to_natural_language(step)
        assert "hello" in nl

    def test_navigate(self) -> None:
        step = _make_step(action=ActionType.NAVIGATE, value="https://example.com")
        nl = step_to_natural_language(step)
        assert "https://example.com" in nl

    def test_steps_to_natural_language(self) -> None:
        steps = [
            _make_step(seq=1, action=ActionType.NAVIGATE, value="https://example.com"),
            _make_step(seq=2, action=ActionType.CLICK, element_text="Login"),
            _make_step(seq=3, action=ActionType.TYPE, value="user@test.com"),
        ]
        result = steps_to_natural_language(steps)
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("1.")
        assert lines[2].startswith("3.")
