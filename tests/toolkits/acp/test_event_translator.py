"""Tests for ACP event_translator — pure function, no I/O needed."""

from __future__ import annotations

import pytest
from acp.schema import SessionNotification

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.acp.server.event_translator import translate_agent_event


class TestTranslateText:
    def test_message_event_produces_notification(self) -> None:
        result = translate_agent_event("s1", {"type": "message", "data": "hello"}, set())
        assert isinstance(result, SessionNotification)

    def test_empty_data_returns_none(self) -> None:
        assert translate_agent_event("s1", {"type": "message", "data": ""}, set()) is None

    def test_non_string_data_returns_none(self) -> None:
        assert translate_agent_event("s1", {"type": "message", "data": 42}, set()) is None

    def test_missing_data_returns_none(self) -> None:
        assert translate_agent_event("s1", {"type": "message"}, set()) is None


class TestTranslateThinking:
    def test_reasoning_event_produces_notification(self) -> None:
        result = translate_agent_event("s1", {"type": "reasoning", "data": "thinking..."}, set())
        assert isinstance(result, SessionNotification)

    def test_empty_reasoning_returns_none(self) -> None:
        assert translate_agent_event("s1", {"type": "reasoning", "data": ""}, set()) is None


class TestTranslateToolCall:
    def test_tool_start_produces_notification_and_tracks(self) -> None:
        active: set[str] = set()
        result = translate_agent_event(
            "s1",
            {"type": "tool_start", "tool_name": "bash", "step_key": "step1"},
            active,
        )
        assert isinstance(result, SessionNotification)
        assert "tc_step1" in active

    def test_repeated_step_key_produces_update(self) -> None:
        active = {"tc_step1"}
        result = translate_agent_event(
            "s1",
            {"type": "tool_start", "tool_name": "bash", "step_key": "step1", "status": "completed"},
            active,
        )
        assert isinstance(result, SessionNotification)

    def test_tasks_steps_event_also_translates(self) -> None:
        active: set[str] = set()
        result = translate_agent_event(
            "s1",
            {"type": "tasks_steps", "tool_name": "web_search", "step_key": "s2"},
            active,
        )
        assert isinstance(result, SessionNotification)
        assert "tc_s2" in active

    def test_missing_tool_name_returns_none(self) -> None:
        assert translate_agent_event("s1", {"type": "tool_start"}, set()) is None

    def test_status_mapping(self) -> None:
        active: set[str] = set()
        translate_agent_event(
            "s1",
            {"type": "tool_start", "tool_name": "t", "step_key": "k", "status": "error"},
            active,
        )
        assert "tc_k" in active

    def test_default_step_key_uses_tool_name(self) -> None:
        active: set[str] = set()
        translate_agent_event(
            "s1",
            {"type": "tool_start", "tool_name": "my_tool"},
            active,
        )
        assert "tc_my_tool" in active


class TestSkipAndUnknownEvents:
    @pytest.mark.parametrize(
        "event_type",
        [
            "message_end",
            "sources",
            "artifacts",
            "artifacts_ready",
            "artifact_content",
            "ui_update",
            "token_usage",
            "status",
            "steering",
            "tool_approval_request",
        ],
    )
    def test_skip_events_return_none(self, event_type: str) -> None:
        assert translate_agent_event("s1", {"type": event_type}, set()) is None

    def test_unknown_event_returns_none(self) -> None:
        assert translate_agent_event("s1", {"type": "completely_unknown"}, set()) is None

    def test_empty_type_returns_none(self) -> None:
        assert translate_agent_event("s1", {"type": ""}, set()) is None

    def test_missing_type_returns_none(self) -> None:
        assert translate_agent_event("s1", {}, set()) is None


class TestAllEventTypesCovered:
    """Verify every AgentEventType is handled (either translated or explicitly skipped)."""

    def test_no_event_type_falls_through_silently(self) -> None:
        active: set[str] = set()
        for evt_type in AgentEventType:
            event: dict[str, object] = {"type": evt_type.value, "data": "test", "tool_name": "t"}
            translate_agent_event("s1", event, active)
