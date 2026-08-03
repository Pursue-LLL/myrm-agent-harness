"""Tests for artifact_focus SSE emission after a successful run."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.artifacts.registry import GeneratedFile
from myrm_agent_harness.agent.streaming.artifact_events import emit_artifact_focus_event
from myrm_agent_harness.agent.streaming.types import AgentEventType


async def _collect_focus(message_id: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    async for event in emit_artifact_focus_event(message_id):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_emit_artifact_focus_event_yields_short_file_id() -> None:
    mock_registry = MagicMock()
    mock_registry.__len__ = MagicMock(return_value=1)
    mock_registry.get_all_files.return_value = [
        GeneratedFile(path="/workspace/out/report.md"),
    ]

    with (
        patch(
            "myrm_agent_harness.agent.streaming.artifact_events.get_artifact_registry",
            return_value=mock_registry,
        ),
        patch(
            "myrm_agent_harness.agent.artifacts.file_id_registry.lookup_short_file_id",
            return_value="@file_001",
        ),
    ):
        events = await _collect_focus("msg-focus-1")

    assert len(events) == 1
    event = events[0]
    assert event["type"] == AgentEventType.ARTIFACT_FOCUS.value
    assert event["message_id"] == "msg-focus-1"
    data = event["data"]
    assert isinstance(data, dict)
    assert data["short_file_id"] == "@file_001"
    assert data["path"] == "/workspace/out/report.md"


@pytest.mark.asyncio
async def test_emit_artifact_focus_event_skips_when_registry_empty() -> None:
    with patch(
        "myrm_agent_harness.agent.streaming.artifact_events.get_artifact_registry",
        return_value=None,
    ):
        events = await _collect_focus("msg-focus-empty")

    assert events == []


@pytest.mark.asyncio
async def test_emit_artifact_focus_event_skips_without_short_file_id() -> None:
    mock_registry = MagicMock()
    mock_registry.__len__ = MagicMock(return_value=1)
    mock_registry.get_all_files.return_value = [
        GeneratedFile(path="/workspace/out/report.md"),
    ]

    with (
        patch(
            "myrm_agent_harness.agent.streaming.artifact_events.get_artifact_registry",
            return_value=mock_registry,
        ),
        patch(
            "myrm_agent_harness.agent.artifacts.file_id_registry.lookup_short_file_id",
            return_value=None,
        ),
    ):
        events = await _collect_focus("msg-focus-no-id")

    assert events == []
