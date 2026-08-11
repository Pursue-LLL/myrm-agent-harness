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

    def test_serialize_step_includes_label(self) -> None:
        step = ActionStep(
            seq=1,
            action=ActionType.SELECT,
            selector="#lang",
            value="en; zh",
            label="English, Chinese",
            url="https://example.com",
            title="",
            timestamp=1000.0,
        )
        d = serialize_step(step)
        assert d["label"] == "English, Chinese"

    def test_serialize_step_label_default_empty(self) -> None:
        step = _make_step()
        d = serialize_step(step)
        assert d["label"] == ""


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
        step = _make_step(
            action=ActionType.CLICK, element_text="Submit", element_role="button"
        )
        nl = step_to_natural_language(step)
        assert "Submit" in nl
        assert "button" in nl

    def test_click_empty_role_falls_back_to_element(self) -> None:
        step = _make_step(
            action=ActionType.CLICK,
            element_text="Submit",
            element_role="",
        )
        nl = step_to_natural_language(step)
        assert nl == 'Click on "Submit" (element)'
        assert "()" not in nl

    def test_dblclick_empty_role_falls_back_to_element(self) -> None:
        step = _make_step(
            action=ActionType.DBLCLICK,
            element_text="Submit",
            element_role="",
        )
        nl = step_to_natural_language(step)
        assert nl == 'Double-click on "Submit" (element)'
        assert "()" not in nl

    def test_type(self) -> None:
        step = _make_step(action=ActionType.TYPE, value="hello", element_role="textbox")
        nl = step_to_natural_language(step)
        assert "hello" in nl

    def test_fill(self) -> None:
        step = _make_step(
            action=ActionType.FILL, value="hello world", element_role="textbox"
        )
        nl = step_to_natural_language(step)
        assert "hello world" in nl

    def test_fill_includes_element_context(self) -> None:
        step = _make_step(
            action=ActionType.FILL,
            value="hello",
            element_text="Username",
            element_role="textbox",
        )
        nl = step_to_natural_language(step)
        assert 'Fill "hello" into textbox "Username"' in nl

    def test_element_context_falls_back_to_selector(self) -> None:
        step = _make_step(
            action=ActionType.TYPE,
            value="hello",
            element_text="",
            element_role="",
            selector="#user-field",
        )
        nl = step_to_natural_language(step)
        assert 'Type "hello" into element "#user-field"' in nl

    def test_credential_label_emits_fill_credential(self) -> None:
        step = _make_step(
            action=ActionType.FILL,
            value="***",
            element_text="Password",
            element_role="textbox",
            is_password=True,
        )
        nl = step_to_natural_language(step, credential_label="login-password")
        assert 'Fill credential "login-password" into textbox "Password"' in nl
        assert "***" not in nl

    def test_credential_label_ignored_for_non_sensitive_step(self) -> None:
        step = _make_step(action=ActionType.FILL, value="hello", element_role="textbox")
        nl = step_to_natural_language(step, credential_label="oops")
        assert "Fill credential" not in nl
        assert 'Fill "hello"' in nl

    def test_navigate(self) -> None:
        step = _make_step(action=ActionType.NAVIGATE, value="https://example.com")
        nl = step_to_natural_language(step)
        assert "https://example.com" in nl

    def test_press_plain_key(self) -> None:
        step = _make_step(action=ActionType.PRESS, value="Enter")
        nl = step_to_natural_language(step)
        assert nl == "Press Enter"

    def test_press_with_modifiers(self) -> None:
        step = ActionStep(
            seq=1,
            action=ActionType.PRESS,
            selector="",
            value="Enter",
            modifiers=["ctrl"],
            url="https://example.com",
            title="",
            timestamp=1000.0,
        )
        nl = step_to_natural_language(step)
        assert nl == "Press Ctrl+Enter"

    def test_serialize_step_includes_modifiers(self) -> None:
        step = ActionStep(
            seq=1,
            action=ActionType.PRESS,
            selector="",
            value="Enter",
            modifiers=["ctrl", "shift"],
            url="https://example.com",
            title="",
            timestamp=1000.0,
        )
        d = serialize_step(step)
        assert d["modifiers"] == ["ctrl", "shift"]

    def test_serialize_step_modifiers_default_empty(self) -> None:
        step = _make_step()
        d = serialize_step(step)
        assert d["modifiers"] == []

    def test_select_without_label(self) -> None:
        step = _make_step(action=ActionType.SELECT, value="option-a")
        nl = step_to_natural_language(step)
        assert nl == 'Select "option-a" from button "Submit"'

    def test_select_with_label(self) -> None:
        step = ActionStep(
            seq=1,
            action=ActionType.SELECT,
            selector="#lang",
            value="en; zh",
            label="English, Chinese",
            url="https://example.com",
            title="",
            timestamp=1000.0,
        )
        nl = step_to_natural_language(step)
        assert nl == 'Select "en; zh" (English, Chinese) from element "#lang"'

    def test_select_multi_value_without_label(self) -> None:
        step = _make_step(action=ActionType.SELECT, value="a; b")
        nl = step_to_natural_language(step)
        assert nl == 'Select "a; b" from button "Submit"'

    def test_select_label_equals_element_text_drops_redundant_context(self) -> None:
        step = ActionStep(
            seq=1,
            action=ActionType.SELECT,
            selector="#lang",
            value="en",
            label="English",
            element_text="English",
            element_role="select",
            url="https://example.com",
            title="",
            timestamp=1000.0,
        )
        nl = step_to_natural_language(step)
        assert nl == 'Select "en" (English)'

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
