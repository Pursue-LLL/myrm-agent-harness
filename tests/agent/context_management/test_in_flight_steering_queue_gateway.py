"""Unit tests for InFlightSteeringQueueGateway."""

import pytest

from myrm_agent_harness.agent.context_management.steering_protocol import (
    InFlightSteeringQueueGateway,
    SteeringConsumptionMode,
    SteeringKind,
)


def test_enqueue_steering_and_peek_queue() -> None:
    """Verify non-blocking steering enqueuing with typed intents."""
    gateway = InFlightSteeringQueueGateway()
    session_id = "sess-steer-001"

    assert gateway.has_pending_steering(session_id) is False

    # Enqueue a live urgent correction
    msg1 = gateway.enqueue_steer(
        session_id=session_id,
        content="Wait, change the return type to Result wrapper!",
        kind=SteeringKind.STEER,
        metadata={"client": "web_chat"},
    )
    assert msg1.kind == SteeringKind.STEER
    assert gateway.has_pending_steering(session_id) is True

    # Enqueue a follow-up
    msg2 = gateway.enqueue_steer(
        session_id=session_id,
        content="Also generate migration test cases afterwards.",
        kind=SteeringKind.FOLLOW_UP,
    )
    assert msg2.kind == SteeringKind.FOLLOW_UP

    pending = gateway.peek_queue(session_id)
    assert len(pending) == 2
    assert pending[0].content == "Wait, change the return type to Result wrapper!"
    assert pending[1].content == "Also generate migration test cases afterwards."


def test_turn_boundary_drain_and_injection_modes() -> None:
    """Verify ONE_AT_A_TIME and ALL drain modes and formatted context injection."""
    gateway = InFlightSteeringQueueGateway()
    session_id = "sess-steer-002"

    gateway.enqueue_steer(session_id, "Correction 1", SteeringKind.STEER)
    gateway.enqueue_steer(session_id, "Correction 2", SteeringKind.STEER)

    base_messages = [
        {"role": "system", "content": "Assistant prompt."},
        {"role": "user", "content": "Initial request."},
        {"role": "assistant", "content": "Executing step 1..."},
    ]

    # Mode: ONE_AT_A_TIME -> drains only the first message
    drain_one = gateway.drain_steering_messages(
        session_id=session_id,
        mode=SteeringConsumptionMode.ONE_AT_A_TIME,
        phase="PRE_TURN",
    )
    assert len(drain_one.drained_messages) == 1
    assert drain_one.drained_messages[0].content == "Correction 1"
    assert len(gateway.peek_queue(session_id)) == 1

    injected_messages = gateway.inject_into_messages(base_messages, drain_one)
    assert len(injected_messages) == 4
    last_msg = injected_messages[-1]
    assert last_msg["role"] == "user"
    assert "[USER STEERING / IN-FLIGHT CORRECTION] [STEER]: Correction 1" in last_msg["content"]

    # Mode: ALL -> drains remaining
    drain_all = gateway.drain_steering_messages(
        session_id=session_id,
        mode=SteeringConsumptionMode.ALL,
        phase="PRE_TURN",
    )
    assert len(drain_all.drained_messages) == 1
    assert drain_all.drained_messages[0].content == "Correction 2"
    assert len(gateway.peek_queue(session_id)) == 0


def test_compaction_safe_secondary_pickup() -> None:
    """Verify secondary pickup catches messages sent while long-running compaction was executing."""
    gateway = InFlightSteeringQueueGateway()
    session_id = "sess-steer-003"

    current_messages = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "Run tests."},
    ]

    # No messages yet
    unchanged, secondary_res = gateway.compaction_safe_pickup(session_id, current_messages)
    assert unchanged == current_messages
    assert secondary_res is None

    # Simulate: user types steering instruction while compaction was running in background
    gateway.enqueue_steer(
        session_id=session_id,
        content="Do not run unit tests on legacy database module!",
        kind=SteeringKind.STEER,
    )

    # Secondary pickup must catch it immediately
    updated_messages, secondary_drain = gateway.compaction_safe_pickup(session_id, current_messages)
    assert secondary_drain is not None
    assert secondary_drain.injection_phase == "POST_COMPACTION_SECONDARY"
    assert len(secondary_drain.drained_messages) == 1
    assert "legacy database module" in secondary_drain.drained_messages[0].content

    # Injected into context
    assert len(updated_messages) == 3
    assert "Do not run unit tests on legacy database module!" in updated_messages[-1]["content"]

    # Queue is now clear
    assert gateway.has_pending_steering(session_id) is False


def test_queue_clear_and_validation() -> None:
    """Verify empty input validation and queue cleanup."""
    gateway = InFlightSteeringQueueGateway()
    session_id = "sess-steer-004"

    # Reject empty or whitespace steering
    with pytest.raises(ValueError, match="cannot be empty"):
        gateway.enqueue_steer(session_id, "   ")

    gateway.enqueue_steer(session_id, "Valid steering")
    assert len(gateway.peek_queue(session_id)) == 1

    cleared_count = gateway.clear_queue(session_id)
    assert cleared_count == 1
    assert len(gateway.peek_queue(session_id)) == 0
