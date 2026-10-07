# ============================================================================
# Unit Tests for In-Flight Steering Queue & Human Co-Steering (Item 161)
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.steering import (
    CoSteeringSessionManager,
    InFlightSteeringMessage,
    InFlightSteeringQueue,
    SteeringInjectionPayload,
    SteeringPriorityKind,
    SteeringQueueSnapshot,
    SteeringStatusKind,
)


def test_enqueue_and_fifo_order() -> None:
    """Validate non-blocking enqueuing and strict FIFO ordering of steering messages."""
    queue = InFlightSteeringQueue(session_id="session-steer-01")

    # 1. Reject empty directive
    with pytest.raises(ValueError):
        queue.enqueue_steering("   ")

    # 2. Enqueue two valid directives
    m1 = queue.enqueue_steering("Stop modifying pyproject.toml, focus on app.py", priority=SteeringPriorityKind.HIGH)
    m2 = queue.enqueue_steering("Also make sure to add type hints", priority=SteeringPriorityKind.NORMAL)

    assert m1.message_id.startswith("steer-")
    assert m1.status == SteeringStatusKind.PENDING
    assert m1.priority == SteeringPriorityKind.HIGH

    pending = queue.get_pending_messages()
    assert len(pending) == 2
    assert pending[0].message_id == m1.message_id
    assert pending[1].message_id == m2.message_id


def test_consume_pending_for_step() -> None:
    """Validate atomic consumption upon micro-step completion and structured prompt injection."""
    queue = InFlightSteeringQueue(session_id="session-steer-02")

    queue.enqueue_steering("Use pathlib instead of os.path", priority=SteeringPriorityKind.HIGH)
    queue.enqueue_steering("Keep existing docstrings intact", priority=SteeringPriorityKind.NORMAL)

    # Micro-step 1 finishes, trigger atomic consumption
    payload = queue.consume_pending_for_step(step_index=1)
    assert payload is not None
    assert payload.count == 2
    assert '<in_flight_human_steering priority="HIGH">' in payload.injected_block
    assert "Use pathlib instead of os.path" in payload.injected_block
    assert "Keep existing docstrings intact" in payload.injected_block
    assert "</in_flight_human_steering>" in payload.injected_block

    # Verify queue is now drained of pending messages
    assert len(queue.get_pending_messages()) == 0

    # Next step call returns None (0 extra token pollution)
    payload_empty = queue.consume_pending_for_step(step_index=2)
    assert payload_empty is None


def test_cancel_steering() -> None:
    """Validate human steering directive recall/cancel before execution injection."""
    queue = InFlightSteeringQueue(session_id="session-steer-03")

    m1 = queue.enqueue_steering("Temporary instruction 1")
    m2 = queue.enqueue_steering("Valid instruction 2")

    # Recall m1
    assert queue.cancel_steering(m1.message_id) is True
    assert queue.cancel_steering("non_existent_id") is False

    # Pending list only contains m2
    pending = queue.get_pending_messages()
    assert len(pending) == 1
    assert pending[0].message_id == m2.message_id

    # Consume for step
    payload = queue.consume_pending_for_step(step_index=1)
    assert payload is not None
    assert payload.count == 1
    assert "Valid instruction 2" in payload.injected_block
    assert "Temporary instruction 1" not in payload.injected_block


def test_co_steering_session_manager_and_snapshot() -> None:
    """Validate multi-session coordinator and comprehensive status snapshot."""
    manager = CoSteeringSessionManager()

    m1 = manager.enqueue(
        session_id="session-multi-A",
        content="Refactor auth to passkey",
        priority=SteeringPriorityKind.HIGH,
        author_device_id="dev-mac",
    )
    m2 = manager.enqueue(
        session_id="session-multi-A",
        content="Cancel this later",
    )
    manager.cancel("session-multi-A", m2.message_id)

    snap = manager.get_snapshot("session-multi-A")
    assert snap is not None
    assert snap.total_enqueued == 2
    assert snap.total_canceled == 1
    assert len(snap.pending_messages) == 1
    assert snap.pending_messages[0].message_id == m1.message_id

    # Consume step
    injected = manager.consume_for_step("session-multi-A", step_index=3)
    assert injected is not None
    assert injected.count == 1

    snap_after = manager.get_snapshot("session-multi-A")
    assert snap_after is not None
    assert snap_after.total_injected == 1
    assert len(snap_after.pending_messages) == 0
