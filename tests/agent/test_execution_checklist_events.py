"""Tests for execution checklist SSE events."""

from __future__ import annotations

from unittest.mock import patch

from myrm_agent_harness.agent.execution_checklist.events import (
    _map_status,
    emit_checklist_events,
)
from myrm_agent_harness.agent.execution_checklist.state import ChecklistItem, ExecutionChecklistState


def test_map_status_cancelled_maps_to_skipped() -> None:
    assert _map_status("cancelled") == "skipped"


def test_emit_checklist_events_dispatches_root_and_items() -> None:
    state = ExecutionChecklistState(
        items=[
            ChecklistItem(id="1", content="Step one", status="in_progress"),
            ChecklistItem(id="2", content="Step two", status="pending"),
        ],
    )
    with patch("myrm_agent_harness.agent.execution_checklist.events.dispatch_custom_event") as mock_dispatch:
        emit_checklist_events(state)
    assert mock_dispatch.call_count == 3


def test_emit_checklist_events_swallows_dispatch_errors() -> None:
    state = ExecutionChecklistState(items=[ChecklistItem(id="1", content="Only", status="pending")])
    with patch(
        "myrm_agent_harness.agent.execution_checklist.events.dispatch_custom_event",
        side_effect=RuntimeError("no callback"),
    ):
        emit_checklist_events(state)
