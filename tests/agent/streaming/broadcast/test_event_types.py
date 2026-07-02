"""Unit tests for AgentEventType, AgentStreamEvent, and observability types.

Covers:
- AgentEventType enum completeness (57 event types)
- AgentStreamEvent serialization/deserialization round-trip
- AgentStreamEvent backward-compatibility dict interface
- ToolCallEventData serialization and frozen immutability
- _truncate_for_event for various input types
- ContextBudgetSnapshot serialization
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.streaming.broadcast.types import ToolCallEventData, _truncate_for_event
from myrm_agent_harness.core.events.types import (
    AgentEventType,
    AgentStreamEvent,
    ContextBudgetSnapshot,
)


class TestAgentEventTypeEnum:
    def test_has_minimum_event_types(self):
        """Must have at least 40+ event types for comprehensive coverage."""
        assert len(AgentEventType) >= 40

    def test_critical_events_present(self):
        """All critical progress/feedback events exist."""
        critical = [
            "TASKS_STEPS",
            "TOOL_HEARTBEAT",
            "TOOL_START",
            "TOOL_END",
            "TOOL_FAILURE",
            "TOOL_STDOUT_CHUNK",
            "TOOL_CANCELLED",
            "STATUS",
            "SUBAGENT_START",
            "SUBAGENT_PROGRESS",
            "SUBAGENT_COMPLETION",
            "BASH_COMMAND_EXECUTED",
            "FILE_DIFF",
            "CAPTCHA_DETECTED",
            "MODEL_ESCALATED",
            "BROWSER_VIEW_UPDATE",
            "DESKTOP_VIEW_UPDATE",
            "REASONING",
            "APPROVAL_REQUIRED",
            "CLARIFICATION_REQUIRED",
        ]
        enum_names = {e.name for e in AgentEventType}
        for name in critical:
            assert name in enum_names, f"Missing critical event: {name}"

    def test_all_values_are_snake_case(self):
        """All event type values should be lowercase snake_case."""
        for event in AgentEventType:
            assert event.value == event.value.lower(), f"{event.name} value not lowercase"
            assert " " not in event.value, f"{event.name} value has spaces"

    def test_no_duplicate_values(self):
        """Event type values must be unique."""
        values = [e.value for e in AgentEventType]
        assert len(values) == len(set(values))


class TestAgentStreamEvent:
    def test_from_dict_round_trip(self):
        raw = {
            "type": "tool_heartbeat",
            "data": {"elapsed_ms": 3000},
            "messageId": "msg_001",
        }
        event = AgentStreamEvent.from_dict(raw)
        assert event.type == "tool_heartbeat"
        assert event.data == {"elapsed_ms": 3000}
        assert event.messageId == "msg_001"
        d = event.to_dict()
        assert d["type"] == "tool_heartbeat"
        assert d["messageId"] == "msg_001"

    def test_from_dict_preserves_extra_fields(self):
        raw = {"type": "status", "custom_field": "hello", "another": 42}
        event = AgentStreamEvent.from_dict(raw)
        assert event.extra_data["custom_field"] == "hello"
        assert event.extra_data["another"] == 42

    def test_to_dict_includes_extra_data(self):
        raw = {"type": "status", "foo": "bar"}
        event = AgentStreamEvent.from_dict(raw)
        d = event.to_dict()
        assert d["foo"] == "bar"

    def test_dict_get_backward_compat(self):
        event = AgentStreamEvent(type="message", data="hello")
        assert event.get("type") == "message"
        assert event.get("data") == "hello"
        assert event.get("nonexistent", "default") == "default"

    def test_dict_subscript_backward_compat(self):
        event = AgentStreamEvent(type="error", error="fail")
        assert event["type"] == "error"
        assert event["error"] == "fail"
        with pytest.raises(KeyError):
            _ = event["nonexistent"]

    def test_to_dict_omits_none_fields(self):
        event = AgentStreamEvent(type="message")
        d = event.to_dict()
        assert "error" not in d
        assert "messageId" not in d
        assert "compression_exhausted" not in d

    def test_enum_type_serializes_to_value(self):
        event = AgentStreamEvent(type=AgentEventType.TOOL_HEARTBEAT, data={"x": 1})
        d = event.to_dict()
        assert d["type"] == "tool_heartbeat"


class TestToolCallEventData:
    def test_frozen_immutability(self):
        data = ToolCallEventData(tool_name="bash", status="started", start_time=1000.0)
        with pytest.raises(AttributeError):
            data.tool_name = "other"  # type: ignore[misc]

    def test_to_dict_minimal(self):
        data = ToolCallEventData(tool_name="web_search", status="started", start_time=1718000000.123)
        d = data.to_dict()
        assert d == {"tool_name": "web_search", "status": "started", "start_time": 1718000000.123}

    def test_to_dict_full(self):
        data = ToolCallEventData(
            tool_name="bash_code_execute_tool",
            status="completed",
            start_time=1000.0,
            end_time=1002.5,
            duration_ms=2500,
            args={"command": "echo hi"},
            result="hi\n",
            session_id="sess_1",
            message_id="msg_1",
            tool_call_id="tc_1",
            version=3,
            evicted_ref="/tmp/output.txt",
        )
        d = data.to_dict()
        assert d["tool_name"] == "bash_code_execute_tool"
        assert d["duration_ms"] == 2500
        assert d["evicted_ref"] == "/tmp/output.txt"
        assert d["version"] == 3

    def test_to_json(self):
        data = ToolCallEventData(tool_name="test", status="failed", start_time=1.0, error="oops")
        j = data.to_json()
        parsed = json.loads(j)
        assert parsed["status"] == "failed"
        assert parsed["error"] == "oops"

    def test_cancel_reason_in_dict(self):
        data = ToolCallEventData(
            tool_name="long_tool",
            status="cancelled",
            start_time=1.0,
            cancel_reason="user_cancelled",
        )
        d = data.to_dict()
        assert d["cancel_reason"] == "user_cancelled"


class TestTruncateForEvent:
    def test_none_passthrough(self):
        assert _truncate_for_event(None) is None

    def test_bool_passthrough(self):
        assert _truncate_for_event(True) is True

    def test_int_passthrough(self):
        assert _truncate_for_event(42) == 42

    def test_short_string_passthrough(self):
        assert _truncate_for_event("hello") == "hello"

    def test_long_string_truncated(self):
        long = "x" * 5000
        result = _truncate_for_event(long, max_bytes=100)
        assert isinstance(result, str)
        assert len(result) < 5000, "Should be smaller than original"
        assert "Truncated" in result or len(result) <= 300

    def test_dict_serialized_and_truncated(self):
        big_dict = {"key": "v" * 5000}
        result = _truncate_for_event(big_dict, max_bytes=100)
        assert isinstance(result, str)
        assert len(result) < 5000, "Should be smaller than original"
        assert "Truncated" in result or len(result) <= 300

    def test_non_serializable_uses_repr(self):
        obj = object()
        result = _truncate_for_event(obj, max_bytes=50)
        assert isinstance(result, str)


class TestContextBudgetSnapshot:
    def test_to_dict(self):
        snap = ContextBudgetSnapshot(
            current_tokens=50000,
            max_context_tokens=128000,
            usage_percent=39.0625,
            health_status="healthy",
        )
        d = snap.to_dict()
        assert d["current_tokens"] == 50000
        assert d["usage_percent"] == 39.1
        assert d["health_status"] == "healthy"
