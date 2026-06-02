"""Tests for core.events — framework-agnostic event types."""

from myrm_agent_harness.core.events import (
    THINKING_TAG_NAMES,
    AgentEventType,
    AgentStreamEvent,
    ApprovalInterceptedEventData,
    ContextBudgetSnapshot,
)


class TestAgentEventType:
    def test_is_str_enum(self) -> None:
        assert isinstance(AgentEventType.MESSAGE, str)
        assert AgentEventType.MESSAGE == "message"

    def test_key_event_types_exist(self) -> None:
        required = {
            "MESSAGE", "MESSAGE_END", "ERROR", "CANCELLED",
            "TOOL_START", "TOOL_END", "TOOL_FAILURE",
            "ARTIFACTS", "TOKEN_USAGE", "REASONING",
            "BROWSER_VIEW_UPDATE",
            "DESKTOP_VIEW_UPDATE",
        }
        actual = {e.name for e in AgentEventType}
        assert required.issubset(actual)

    def test_browser_view_update_value(self) -> None:
        assert AgentEventType.BROWSER_VIEW_UPDATE == "browser_view_update"
        assert AgentEventType.BROWSER_VIEW_UPDATE.value == "browser_view_update"

    def test_browser_view_update_stream_event_roundtrip(self) -> None:
        evt = AgentStreamEvent(
            type=AgentEventType.BROWSER_VIEW_UPDATE,
            data={
                "screenshot_base64": "iVBOR...",
                "mime_type": "image/jpeg",
                "refs": {"ref1": {"role": "button", "name": "Submit"}},
                "page_url": "https://example.com",
            },
        )
        d = evt.to_dict()
        assert d["type"] == "browser_view_update"
        assert d["data"]["refs"]["ref1"]["role"] == "button"

        restored = AgentStreamEvent.from_dict(d)
        assert restored.type == "browser_view_update"
        assert restored.data["page_url"] == "https://example.com"

    def test_desktop_view_update_value(self) -> None:
        assert AgentEventType.DESKTOP_VIEW_UPDATE == "desktop_view_update"
        assert AgentEventType.DESKTOP_VIEW_UPDATE.value == "desktop_view_update"

    def test_desktop_view_update_stream_event_roundtrip(self) -> None:
        evt = AgentStreamEvent(
            type=AgentEventType.DESKTOP_VIEW_UPDATE,
            data={
                "screenshot_base64": "iVBOR...",
                "mime_type": "image/jpeg",
                "refs": {"d1": {"role": "button", "name": "Save"}},
                "app_name": "Safari",
                "window_title": "Example",
                "scope": "foreground",
                "needs_permission": False,
                "viewport_width": 1920,
                "viewport_height": 1080,
            },
        )
        d = evt.to_dict()
        assert d["type"] == "desktop_view_update"
        assert d["data"]["refs"]["d1"]["role"] == "button"

        restored = AgentStreamEvent.from_dict(d)
        assert restored.type == "desktop_view_update"
        assert restored.data["app_name"] == "Safari"


class TestAgentStreamEvent:
    def test_basic_creation(self) -> None:
        evt = AgentStreamEvent(type=AgentEventType.MESSAGE, data="hello")
        assert evt.type == AgentEventType.MESSAGE
        assert evt.data == "hello"

    def test_from_dict(self) -> None:
        raw = {"type": "message", "data": "hello", "custom_field": 42}
        evt = AgentStreamEvent.from_dict(raw)
        assert evt.type == "message"
        assert evt.data == "hello"
        assert evt.extra_data["custom_field"] == 42

    def test_to_dict(self) -> None:
        evt = AgentStreamEvent(
            type=AgentEventType.ERROR,
            error="fail",
            error_type="timeout",
        )
        d = evt.to_dict()
        assert d["type"] == "error"
        assert d["error"] == "fail"
        assert d["error_type"] == "timeout"
        assert "data" not in d

    def test_to_dict_with_extra(self) -> None:
        evt = AgentStreamEvent(type="custom")
        evt.extra_data["foo"] = "bar"
        d = evt.to_dict()
        assert d["foo"] == "bar"

    def test_get_backward_compat(self) -> None:
        evt = AgentStreamEvent(type=AgentEventType.MESSAGE, data="x")
        assert evt.get("data") == "x"
        assert evt.get("missing", "default") == "default"

    def test_getitem_backward_compat(self) -> None:
        evt = AgentStreamEvent(type=AgentEventType.MESSAGE, data="x")
        assert evt["data"] == "x"
        evt.extra_data["custom"] = 1
        assert evt["custom"] == 1

    def test_getitem_keyerror(self) -> None:
        evt = AgentStreamEvent(type="test")
        import pytest
        with pytest.raises(KeyError):
            _ = evt["nonexistent"]

    def test_from_dict_unknown_type(self) -> None:
        evt = AgentStreamEvent.from_dict({})
        assert evt.type == "unknown"

    def test_to_dict_with_error_type(self) -> None:
        evt = AgentStreamEvent(
            type=AgentEventType.ERROR,
            error="timeout",
            error_type="TimeoutError",
        )
        d = evt.to_dict()
        assert d["error_type"] == "TimeoutError"

    def test_to_dict_with_compression_exhausted(self) -> None:
        evt = AgentStreamEvent(
            type=AgentEventType.MESSAGE_END,
            compression_exhausted=True,
        )
        d = evt.to_dict()
        assert d["compression_exhausted"] is True

    def test_to_dict_all_optional_fields(self) -> None:
        evt = AgentStreamEvent(
            type=AgentEventType.MESSAGE,
            data="content",
            messageId="msg-1",
            error="err",
            error_type="ValueError",
            compression_exhausted=False,
        )
        d = evt.to_dict()
        assert d["data"] == "content"
        assert d["messageId"] == "msg-1"
        assert d["error"] == "err"
        assert d["error_type"] == "ValueError"
        assert d["compression_exhausted"] is False


class TestContextBudgetSnapshot:
    def test_to_dict(self) -> None:
        snap = ContextBudgetSnapshot(
            current_tokens=5000,
            max_context_tokens=128000,
            usage_percent=3.90625,
            health_status="healthy",
        )
        d = snap.to_dict()
        assert d["current_tokens"] == 5000
        assert d["usage_percent"] == 3.9
        assert d["health_status"] == "healthy"


class TestApprovalInterceptedEventData:
    def test_creation(self) -> None:
        data = ApprovalInterceptedEventData(decision="approved")
        assert data.decision == "approved"
        assert data.original_text is None

    def test_with_original_text(self) -> None:
        data = ApprovalInterceptedEventData(
            decision="rejected", original_text="rm -rf /"
        )
        assert data.original_text == "rm -rf /"


class TestThinkingTagNames:
    def test_is_tuple(self) -> None:
        assert isinstance(THINKING_TAG_NAMES, tuple)
        assert len(THINKING_TAG_NAMES) > 0

    def test_contains_common_tags(self) -> None:
        assert "think" in THINKING_TAG_NAMES
        assert "thinking" in THINKING_TAG_NAMES
        assert "reasoning" in THINKING_TAG_NAMES


class TestReExportTypeIdentity:
    def test_event_type_identity(self) -> None:
        from myrm_agent_harness.agent.streaming.types import (
            AgentEventType as AgentAgentEventType,
        )

        assert AgentEventType is AgentAgentEventType

    def test_stream_event_identity(self) -> None:
        from myrm_agent_harness.agent.streaming.types import (
            AgentStreamEvent as AgentAgentStreamEvent,
        )

        assert AgentStreamEvent is AgentAgentStreamEvent

    def test_isinstance_cross_module(self) -> None:
        from myrm_agent_harness.agent.streaming.types import (
            AgentStreamEvent as AgentEvt,
        )

        evt = AgentStreamEvent(type=AgentEventType.MESSAGE)
        assert isinstance(evt, AgentEvt)
