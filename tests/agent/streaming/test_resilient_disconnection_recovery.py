"""Unit tests for resilient event replay buffer and disconnection recovery suite.

Verifies:
- Monotonic sequence identifier allocation and JSON roundtrip serialization.
- Bounded circular eviction by event capacity and byte limits.
- Precise replay query status classification (CONTINUOUS, GAP_DETECTED, EMPTY, UP_TO_DATE).
- Asynchronous subscriber catch-up replay and live event dispatching.
- Heartbeat emission and silent disconnection detection.
- Two-phase reconnect handshake leading to either CONNECTED or RESYNC_REQUIRED.
- Offline action staging and atomic FIFO draining upon connection self-healing.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.streaming.recovery.disconnection_recovery import (
    ResilientDisconnectionRecoveryManager,
)
from myrm_agent_harness.agent.streaming.recovery.recovery_types import (
    StructuredStreamEvent,
    dict_to_event,
    event_to_dict,
)
from myrm_agent_harness.agent.streaming.recovery.replay_buffer import (
    CircularEventReplayBuffer,
)


def test_event_serialization_and_monotonic_ids() -> None:
    event = StructuredStreamEvent(
        sequence_id=42,
        event_type="token_chunk",
        stream_id="stream-xyz-987",
        payload={"delta": "Hello world", "index": 0},
        timestamp=1700000000.5,
        estimated_bytes=256,
    )

    d = event_to_dict(event)
    assert d["sequence_id"] == 42
    assert d["event_type"] == "token_chunk"
    assert d["stream_id"] == "stream-xyz-987"

    restored = dict_to_event(d)
    assert restored.sequence_id == event.sequence_id
    assert restored.event_type == event.event_type
    assert restored.payload == event.payload
    assert restored.timestamp == event.timestamp


@pytest.mark.asyncio
async def test_circular_eviction_by_capacity() -> None:
    buffer = CircularEventReplayBuffer("test-stream", max_events=3)

    e1 = await buffer.append_event("token", "chunk 1")
    e2 = await buffer.append_event("token", "chunk 2")
    e3 = await buffer.append_event("token", "chunk 3")

    assert e1.sequence_id == 1
    assert e2.sequence_id == 2
    assert e3.sequence_id == 3
    assert buffer.retained_count == 3
    assert buffer.latest_sequence_id == 3

    # Adding 4th and 5th events evicts oldest
    e4 = await buffer.append_event("token", "chunk 4")
    e5 = await buffer.append_event("token", "chunk 5")

    assert e4.sequence_id == 4
    assert e5.sequence_id == 5
    assert buffer.retained_count == 3
    assert buffer.latest_sequence_id == 5

    # Events 1 and 2 are evicted; querying last_seq=1 results in GAP_DETECTED
    batch_gap = await buffer.replay_since(1)
    assert batch_gap.status == "GAP_DETECTED"
    assert batch_gap.oldest_retained_seq == 3
    assert batch_gap.latest_retained_seq == 5
    assert len(batch_gap.events) == 0

    # Querying last_seq=2 (immediately preceding oldest=3) should yield CONTINUOUS [3, 4, 5]
    batch_cont = await buffer.replay_since(2)
    assert batch_cont.status == "CONTINUOUS"
    assert len(batch_cont.events) == 3
    assert [evt.sequence_id for evt in batch_cont.events] == [3, 4, 5]


@pytest.mark.asyncio
async def test_circular_eviction_by_byte_limit() -> None:
    # 350 bytes limit forces eviction of small payloads quickly
    buffer = CircularEventReplayBuffer("byte-stream", max_events=100, max_bytes=350)

    for i in range(10):
        await buffer.append_event("token", f"payload padding value {i}")

    assert buffer.current_bytes <= 350
    assert buffer.retained_count < 10


@pytest.mark.asyncio
async def test_replay_since_boundary_conditions() -> None:
    buffer = CircularEventReplayBuffer("boundary-stream", max_events=10)

    # Empty buffer
    empty_batch = await buffer.replay_since(0)
    assert empty_batch.status == "EMPTY"
    assert len(empty_batch.events) == 0

    # Populate 3 events
    await buffer.append_event("tool_call", "tool 1")
    await buffer.append_event("tool_call", "tool 2")
    await buffer.append_event("tool_call", "tool 3")

    # Client is up-to-date
    up_to_date_batch = await buffer.replay_since(3)
    assert up_to_date_batch.status == "UP_TO_DATE"
    assert len(up_to_date_batch.events) == 0

    # Client asks for future sequence
    future_batch = await buffer.replay_since(99)
    assert future_batch.status == "GAP_DETECTED"

    # Client has received seq 1, requests next
    partial_batch = await buffer.replay_since(1)
    assert partial_batch.status == "CONTINUOUS"
    assert [evt.sequence_id for evt in partial_batch.events] == [2, 3]


@pytest.mark.asyncio
async def test_subscriber_catchup_and_live_dispatch() -> None:
    buffer = CircularEventReplayBuffer("sub-stream", max_events=10)

    await buffer.append_event("token", "initial-1")
    await buffer.append_event("token", "initial-2")

    received_events: list[StructuredStreamEvent] = []

    async def _subscriber_task() -> None:
        async for evt in buffer.subscribe(last_sequence_id=1, heartbeat_interval=1.0):
            if evt.event_type != "heartbeat":
                received_events.append(evt)
            if evt.payload == "final-chunk":
                break

    task = asyncio.create_task(_subscriber_task())
    # Give subscriber loop a moment to catch up from seq 1
    await asyncio.sleep(0.05)

    # Append live event
    await buffer.append_event("token", "final-chunk")
    await asyncio.wait_for(task, timeout=2.0)

    assert len(received_events) == 2
    assert received_events[0].sequence_id == 2
    assert received_events[0].payload == "initial-2"
    assert received_events[1].sequence_id == 3
    assert received_events[1].payload == "final-chunk"


@pytest.mark.asyncio
async def test_disconnection_manager_lifecycle_and_heartbeat_timeout() -> None:
    mgr = ResilientDisconnectionRecoveryManager("session-101")
    assert mgr.state == "CONNECTED"
    assert mgr.disconnected_duration == 0.0

    # Trigger heartbeat timeout
    await mgr.record_heartbeat()
    # Fast heartbeat timeout check with 0s threshold
    is_timed_out = await mgr.check_heartbeat_timeout(timeout_seconds=-0.01)
    assert is_timed_out
    assert mgr.state == "DISCONNECTED"
    assert mgr.disconnected_duration > 0.0

    # Inbound ping automatically restores connection
    await mgr.record_heartbeat()
    assert mgr.state == "CONNECTED"
    assert mgr.disconnected_duration == 0.0


@pytest.mark.asyncio
async def test_two_phase_reconnect_handshake() -> None:
    buffer = CircularEventReplayBuffer("handshake-stream", max_events=5)
    mgr = ResilientDisconnectionRecoveryManager("handshake-stream", replay_buffer=buffer)

    for i in range(1, 4):
        await buffer.append_event("data", f"val-{i}")

    # Mark offline
    await mgr.mark_disconnected("wifi_drop")
    assert mgr.state == "DISCONNECTED"

    # Reconnect with continuous sequence
    state, batch = await mgr.handle_reconnect(client_last_seq=1)
    assert state == "CONNECTED"
    assert batch.status == "CONTINUOUS"
    assert [e.sequence_id for e in batch.events] == [2, 3]

    # Now simulate excessive lag causing eviction
    for i in range(4, 15):
        await buffer.append_event("data", f"val-{i}")

    # Reconnect with ancient sequence (seq 2 was evicted)
    state_gap, batch_gap = await mgr.handle_reconnect(client_last_seq=2)
    assert state_gap == "RESYNC_REQUIRED"
    assert batch_gap.status == "GAP_DETECTED"


@pytest.mark.asyncio
async def test_offline_action_staging_and_flush() -> None:
    mgr = ResilientDisconnectionRecoveryManager("staging-session", max_staged_actions=3)

    # Disconnect
    await mgr.mark_disconnected("network_offline")

    # Stage actions while offline
    a1 = await mgr.stage_offline_action("send_chat", {"text": "hello 1"})
    a2 = await mgr.stage_offline_action("send_chat", {"text": "hello 2"})
    a3 = await mgr.stage_offline_action("submit_feedback", {"rating": 5})

    assert mgr.staged_actions_count == 3

    # 4th action causes eviction of the oldest staged action (capacity = 3)
    a4 = await mgr.stage_offline_action("send_chat", {"text": "hello 4"})
    assert mgr.staged_actions_count == 3

    # Flush all staged actions atomically
    flushed = await mgr.flush_staged_actions()
    assert len(flushed) == 3
    assert a1.action_id not in [a.action_id for a in flushed]
    assert [a.action_id for a in flushed] == [a2.action_id, a3.action_id, a4.action_id]
    assert mgr.staged_actions_count == 0
