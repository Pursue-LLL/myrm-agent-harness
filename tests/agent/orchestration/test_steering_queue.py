"""Unit tests for agent.orchestration.steering inbound queue."""

from __future__ import annotations

from myrm_agent_harness.agent.orchestration.steering import (
    MAX_NOTE_CHARS,
    SteeringQueue,
    SteeringStatus,
    build_steering_context_block,
)


def test_enqueue_preserves_arrival_order() -> None:
    queue = SteeringQueue()
    first = queue.enqueue("sess-1", "pivot to file X")
    second = queue.enqueue("sess-1", "skip the tests")
    pending = queue.pending("sess-1")
    assert [note.note_id for note in pending] == [first.note_id, second.note_id]
    assert first.seq < second.seq


def test_enqueue_rejects_empty_text() -> None:
    queue = SteeringQueue()
    try:
        queue.enqueue("sess-1", "   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty steering text")


def test_enqueue_rejects_oversized_text() -> None:
    queue = SteeringQueue()
    try:
        queue.enqueue("sess-1", "x" * (MAX_NOTE_CHARS + 1))
    except ValueError:
        return
    raise AssertionError("expected ValueError for oversized steering text")


def test_duplicate_collapses_onto_original() -> None:
    queue = SteeringQueue()
    first = queue.enqueue("sess-1", "focus on implementation", agent_id="main")
    second = queue.enqueue("sess-1", "focus on implementation", agent_id="main")
    assert second.note_id == first.note_id
    assert len(queue.pending("sess-1")) == 1
    assert queue.metrics_snapshot().dedup_dropped == 1


def test_duplicate_scope_includes_agent() -> None:
    queue = SteeringQueue()
    first = queue.enqueue("sess-1", "check X", agent_id="agent-a")
    second = queue.enqueue("sess-1", "check X", agent_id="agent-b")
    assert second.note_id != first.note_id


def test_bounded_eviction_drops_oldest_with_audit() -> None:
    queue = SteeringQueue(max_notes=2)
    queue.enqueue("sess-1", "first")
    queue.enqueue("sess-1", "second")
    queue.enqueue("sess-1", "third")
    pending = queue.pending("sess-1")
    assert [note.text for note in pending] == ["second", "third"]
    assert len(queue.evicted_ids()) == 1
    assert queue.metrics_snapshot().evicted == 1


def test_drain_marks_injected_and_counts_metrics() -> None:
    queue = SteeringQueue()
    queue.enqueue("sess-1", "note-a")
    queue.enqueue("sess-2", "note-b")
    drained = queue.drain_for_boundary("sess-1")
    assert [note.text for note in drained] == ["note-a"]
    assert all(note.status == SteeringStatus.INJECTED for note in drained)
    assert queue.pending("sess-1") == []
    assert queue.pending("sess-2") != []
    assert queue.metrics_snapshot().injected == 1


def test_publish_defaults_closed_until_authorized() -> None:
    queue = SteeringQueue()
    note = queue.enqueue("sess-1", "transcript candidate")
    assert note.publish_authorized is False
    assert queue.authorize_publish("missing-id") is False
    assert queue.authorize_publish(note.note_id) is True
    assert note.publish_authorized is True


def test_context_block_labels_side_channel() -> None:
    queue = SteeringQueue()
    note = queue.enqueue("sess-1", "pivot to file X", quoted_ref="msg-42")
    block = build_steering_context_block([note])
    assert "queued during active run" in block
    assert "pivot to file X" in block
    assert "msg-42" in block
    assert "does not authorize" in block


def test_snapshot_round_trip_recovers_restart() -> None:
    queue = SteeringQueue()
    queue.enqueue("sess-1", "keep me", agent_id="main")
    queue.enqueue("sess-1", "keep me", agent_id="main")
    snapshot = queue.to_snapshot()
    restored = SteeringQueue.from_snapshot(snapshot)
    pending = restored.pending("sess-1")
    assert [note.text for note in pending] == ["keep me"]
    assert restored.metrics_snapshot().received == 2
    assert restored.metrics_snapshot().dedup_dropped == 1


def test_snapshot_excludes_consumed_notes() -> None:
    queue = SteeringQueue()
    queue.enqueue("sess-1", "consumed-note")
    queue.enqueue("sess-1", "pending-note")
    drained = queue.drain_for_boundary("sess-1", max_notes=1)
    assert [note.text for note in drained] == ["consumed-note"]
    snapshot = queue.to_snapshot()
    raw_notes = snapshot["notes"]
    assert isinstance(raw_notes, list)
    assert [item["text"] for item in raw_notes if isinstance(item, dict)] == ["pending-note"]
    assert queue.metrics_snapshot().injected == 1


def test_authorize_rejects_evicted_note() -> None:
    queue = SteeringQueue(max_notes=1)
    first = queue.enqueue("sess-1", "first")
    queue.enqueue("sess-1", "second")
    assert first.status == SteeringStatus.EVICTED
    assert queue.authorize_publish(first.note_id) is False


def test_consumed_history_stays_bounded() -> None:
    queue = SteeringQueue(max_notes=2)
    for index in range(10):
        queue.enqueue("sess-1", f"note-{index}")
        queue.drain_for_boundary("sess-1")
    snapshot = queue.to_snapshot()
    raw_notes = snapshot["notes"]
    assert isinstance(raw_notes, list)
    assert len(raw_notes) == 0


def test_drain_into_token_feeds_live_mechanism() -> None:
    from myrm_agent_harness.agent.orchestration.steering import drain_into_token
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    queue = SteeringQueue()
    token = SteeringToken()
    queue.enqueue("sess-1", "pivot to file X")
    assert drain_into_token(queue, token, "sess-1") == 1
    assert token.has_pending is True
    assert queue.pending("sess-1") == []
    assert queue.metrics_snapshot().injected == 1
    assert drain_into_token(queue, token, "sess-1") == 0


def test_drain_into_token_respects_max_notes() -> None:
    from myrm_agent_harness.agent.orchestration.steering import drain_into_token
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    queue = SteeringQueue()
    token = SteeringToken()
    queue.enqueue("sess-1", "first")
    queue.enqueue("sess-1", "second")
    assert drain_into_token(queue, token, "sess-1", max_notes=1) == 1
    assert len(queue.pending("sess-1")) == 1


def test_queue_module_has_no_tool_registry_coupling() -> None:
    import myrm_agent_harness.agent.orchestration.steering as module

    assert "tool_management" not in dir(module)
    assert not hasattr(module, "register_tool")
