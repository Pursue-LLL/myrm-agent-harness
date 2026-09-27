"""Tests for PiSessionEntryCustomVsCustomMessageSeparation.

Verifies:
1. AgentEventType.CUSTOM and CUSTOM_MESSAGE enumeration and persistence.
2. CustomStatePayload and CustomMessagePayload strongly-typed schema serialization.
3. FileEventLogBackend.get_latest_custom_state reverse-scan short-circuit behavior.
4. trace_builder aggregation of custom states into ExecutionTrace.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.trace_builder import build_trace
from myrm_agent_harness.agent.event_log.types import (
    CustomMessagePayload,
    CustomStatePayload,
    EventPayload,
    StructuredEvent,
    get_persistent_event_types,
)
from myrm_agent_harness.core.events.types import AgentEventType


def test_custom_event_types_in_persistent_set() -> None:
    """AgentEventType.CUSTOM and CUSTOM_MESSAGE must be persistent."""
    persistent = get_persistent_event_types()
    assert AgentEventType.CUSTOM.value in persistent
    assert AgentEventType.CUSTOM_MESSAGE.value in persistent
    assert "custom" in persistent
    assert "custom_message" in persistent


def test_custom_payload_schemas() -> None:
    """Verify serialization and validation of custom payloads."""
    state_payload = CustomStatePayload(
        custom_type="doc_index",
        state={"indexed_files": ["a.py", "b.py"], "version": 2},
    )
    dumped_state = state_payload.model_dump()
    assert dumped_state["custom_type"] == "doc_index"
    assert dumped_state["state"]["version"] == 2

    msg_payload = CustomMessagePayload(
        custom_type="security_gate",
        content="Read-only branch active",
        display=True,
        retention="ephemeral",
        details={"branch": "release-frozen"},
    )
    dumped_msg = msg_payload.model_dump()
    assert dumped_msg["custom_type"] == "security_gate"
    assert dumped_msg["display"] is True
    assert dumped_msg["retention"] == "ephemeral"
    assert dumped_msg["details"]["branch"] == "release-frozen"


@pytest.mark.asyncio
async def test_get_latest_custom_state_reverse_short_circuit(tmp_path: Path) -> None:
    """Verify get_latest_custom_state finds latest state with reverse scan."""
    session_id = "test-session-custom-state"
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=session_id)

    # Append events with multiple custom types across time
    t0 = time.time()
    events = [
        StructuredEvent(
            sequence=1,
            timestamp=t0,
            event_type="custom",
            session_id=session_id,
            data=EventPayload(custom_type="plugin_a", state={"v": 1}),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=t0 + 0.1,
            event_type="custom",
            session_id=session_id,
            data=EventPayload(custom_type="plugin_b", state={"step": "init"}),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=t0 + 0.2,
            event_type="custom_message",
            session_id=session_id,
            data=EventPayload(custom_type="plugin_b", content="hello"),
        ),
        StructuredEvent(
            sequence=4,
            timestamp=t0 + 0.3,
            event_type="custom",
            session_id=session_id,
            data=EventPayload(custom_type="plugin_a", state={"v": 2, "ready": True}),
        ),
    ]
    await backend.append(events)

    # 1. Query specific custom_type: should short-circuit and find sequence 4 (v=2)
    state_a = await backend.get_latest_custom_state(session_id, custom_type="plugin_a")
    assert state_a == {"v": 2, "ready": True}

    # 2. Query other plugin: sequence 2
    state_b = await backend.get_latest_custom_state(session_id, custom_type="plugin_b")
    assert state_b == {"step": "init"}

    # 3. Query nonexistent plugin: empty dict
    state_c = await backend.get_latest_custom_state(session_id, custom_type="nonexistent")
    assert state_c == {}

    # 4. Query all plugins (custom_type=None): consolidated latest map
    all_states = await backend.get_latest_custom_state(session_id)
    assert all_states == {
        "plugin_a": {"v": 2, "ready": True},
        "plugin_b": {"step": "init"},
    }

    # 5. Non-existent session
    missing_session_state = await backend.get_latest_custom_state("no-such-session")
    assert missing_session_state == {}


@pytest.mark.asyncio
async def test_trace_builder_aggregates_custom_states(tmp_path: Path) -> None:
    """ExecutionTrace must capture custom_states from event log."""
    session_id = "test-session-trace-custom"
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=session_id)

    events = [
        StructuredEvent(
            sequence=1,
            timestamp=1000.0,
            event_type="task_start",
            session_id=session_id,
            data=EventPayload(input="Solve task"),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=1001.0,
            event_type="custom",
            session_id=session_id,
            data=EventPayload(custom_type="git_scanner", state={"branch": "main", "clean": True}),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=1002.0,
            event_type="custom_message",
            session_id=session_id,
            data=EventPayload(custom_type="git_scanner", content="Clean branch verified", display=True),
        ),
    ]
    await backend.append(events)

    trace = await build_trace(backend, session_id)
    assert "git_scanner" in trace.custom_states
    assert trace.custom_states["git_scanner"] == {"branch": "main", "clean": True}

    trace_dict = trace.to_dict()
    assert "custom_states" in trace_dict
    assert trace_dict["custom_states"]["git_scanner"] == {"branch": "main", "clean": True}


@pytest.mark.asyncio
async def test_get_latest_custom_state_time_travel_sequence_guard(tmp_path: Path) -> None:
    """Time-travel sequence guard must ignore future events when max_sequence is specified."""
    session_id = "test-session-time-travel"
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=session_id)

    # Simulate sequence:
    # seq 1: plugin_cfg initialized with v1
    # seq 2: plugin_cfg updated to v2
    # seq 3: plugin_cfg updated to v3 (simulating a turn that gets rolled back)
    events = [
        StructuredEvent(
            sequence=1,
            timestamp=1000.0,
            event_type="custom",
            session_id=session_id,
            data=EventPayload(custom_type="config_plugin", state={"v": 1, "active": True}),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=1001.0,
            event_type="custom",
            session_id=session_id,
            data=EventPayload(custom_type="config_plugin", state={"v": 2, "active": True}),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=1002.0,
            event_type="custom",
            session_id=session_id,
            data=EventPayload(custom_type="config_plugin", state={"v": 3, "active": False}),
        ),
    ]
    await backend.append(events)

    # 1. Unconstrained lookup returns latest physical state (v3)
    latest_state = await backend.get_latest_custom_state(session_id, "config_plugin")
    assert latest_state == {"v": 3, "active": False}

    # 2. Time-travel query at max_sequence=2 must ignore sequence 3 and return v2
    rollback_state = await backend.get_latest_custom_state(session_id, "config_plugin", max_sequence=2)
    assert rollback_state == {"v": 2, "active": True}

    # 3. Time-travel query at max_sequence=1 must ignore sequences 2 and 3 and return v1
    v1_state = await backend.get_latest_custom_state(session_id, "config_plugin", max_sequence=1)
    assert v1_state == {"v": 1, "active": True}

    # 4. Time-travel query before any custom event (max_sequence=0) returns empty
    pre_state = await backend.get_latest_custom_state(session_id, "config_plugin", max_sequence=0)
    assert pre_state == {}
