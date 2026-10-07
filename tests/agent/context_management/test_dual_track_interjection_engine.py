"""Tests for Long-Running Task Dual-Track Interjection and Preemption Queue Suite (Item 212).

Verifies step-boundary immediate interjection draining, priority queue preemption,
task cancellation, expiration, bounded capacities, and session isolation.
"""

from __future__ import annotations

import time

from myrm_agent_harness.agent.context_management.dual_track_interjection.dual_track_interjection_engine import (
    DualTrackInterventionCoordinator,
)
from myrm_agent_harness.agent.context_management.dual_track_interjection.dual_track_interjection_types import (
    DualTrackInterventionConfig,
    InterventionStatus,
    InterventionTrack,
    PreemptionQueueSnapshot,
    StepBoundaryInjectionResult,
    UserInterventionDirective,
)


def test_immediate_interjection_submission_and_step_boundary_drain() -> None:
    """Verifies immediate interjections are prioritized, drained at step boundaries, and marked consumed."""
    coordinator = DualTrackInterventionCoordinator()
    session_id = "session_interject_alpha"

    # Submit low priority directive first, then high priority
    d1: UserInterventionDirective = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.IMMEDIATE_INTERJECT,
        prompt_text="Remember to add debug logging for database queries.",
        priority=50,
    )
    d2: UserInterventionDirective = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.IMMEDIATE_INTERJECT,
        prompt_text="CRITICAL: Do not overwrite the existing auth table migration.",
        priority=200,
    )

    assert d1.status == InterventionStatus.PENDING
    assert d2.status == InterventionStatus.PENDING

    # Drain at step boundary
    result: StepBoundaryInjectionResult = coordinator.drain_step_boundary_interjections(session_id)

    assert result.interjection_applied is True
    assert result.injected_message is not None
    assert result.injected_message["role"] == "user"
    content = str(result.injected_message["content"])

    assert "<human-interjection>" in content
    assert "</human-interjection>" in content
    # High priority should appear before low priority
    idx_d2 = content.find("Do not overwrite the existing auth table migration")
    idx_d1 = content.find("add debug logging for database queries")
    assert idx_d2 != -1 and idx_d1 != -1
    assert idx_d2 < idx_d1

    assert result.consumed_directive_ids == [d2.directive_id, d1.directive_id]
    assert d1.status == InterventionStatus.CONSUMED
    assert d2.status == InterventionStatus.CONSUMED
    assert d1.consumed_at is not None
    assert d2.consumed_at is not None

    # Subsequent drain should be empty
    second_drain = coordinator.drain_step_boundary_interjections(session_id)
    assert second_drain.interjection_applied is False
    assert second_drain.injected_message is None
    assert second_drain.consumed_directive_ids == []


def test_queue_preemption_submission_priority_and_sequential_pop() -> None:
    """Verifies tasks in the preemption queue are prioritized and popped sequentially upon task completion."""
    coordinator = DualTrackInterventionCoordinator()
    session_id = "session_preempt_beta"

    # Submit three preemptive tasks with varying priorities
    q1 = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.QUEUE_PREEMPTION,
        prompt_text="Task Normal: Generate unit tests for api_v1 routes.",
        priority=100,
    )
    q2 = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.QUEUE_PREEMPTION,
        prompt_text="Task Urgent: Run smoke test on docker container.",
        priority=300,
    )
    q3 = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.QUEUE_PREEMPTION,
        prompt_text="Task Low: Update documentation README.",
        priority=10,
    )

    # Check snapshot
    snapshot: PreemptionQueueSnapshot = coordinator.get_preemption_queue_snapshot(session_id)
    assert snapshot.session_id == session_id
    assert snapshot.queue_length == 3
    # Top task in snapshot should be q2
    assert snapshot.queued_directives[0].directive_id == q2.directive_id
    assert snapshot.queued_directives[1].directive_id == q1.directive_id
    assert snapshot.queued_directives[2].directive_id == q3.directive_id

    # Pop sequentially
    first_popped = coordinator.pop_next_preemption_task(session_id)
    assert first_popped is not None
    assert first_popped.directive_id == q2.directive_id
    assert first_popped.status == InterventionStatus.CONSUMED

    second_popped = coordinator.pop_next_preemption_task(session_id)
    assert second_popped is not None
    assert second_popped.directive_id == q1.directive_id

    third_popped = coordinator.pop_next_preemption_task(session_id)
    assert third_popped is not None
    assert third_popped.directive_id == q3.directive_id

    # Queue should now be empty
    assert coordinator.pop_next_preemption_task(session_id) is None
    empty_snap = coordinator.get_preemption_queue_snapshot(session_id)
    assert empty_snap.queue_length == 0


def test_intervention_cancellation_and_expiration() -> None:
    """Verifies directive cancellation and expiration handling."""
    coordinator = DualTrackInterventionCoordinator()
    session_id = "session_cancel_gamma"

    interject = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.IMMEDIATE_INTERJECT,
        prompt_text="Accidental instruction to be cancelled.",
    )
    preempt = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.QUEUE_PREEMPTION,
        prompt_text="Accidental task to be cancelled.",
    )

    # Cancel both
    assert coordinator.cancel_intervention(session_id, interject.directive_id) is True
    assert coordinator.cancel_intervention(session_id, preempt.directive_id) is True
    # Cancelling again returns False
    assert coordinator.cancel_intervention(session_id, interject.directive_id) is False

    assert interject.status == InterventionStatus.CANCELLED
    assert preempt.status == InterventionStatus.CANCELLED

    # Neither should be consumed
    drain_res = coordinator.drain_step_boundary_interjections(session_id)
    assert drain_res.interjection_applied is False
    assert coordinator.pop_next_preemption_task(session_id) is None

    # Expiration test
    expired_cfg = DualTrackInterventionConfig(expiration_seconds=0.001)
    exp_dir = coordinator.submit_intervention(
        session_id=session_id,
        track=InterventionTrack.IMMEDIATE_INTERJECT,
        prompt_text="Will expire quickly.",
    )
    time.sleep(0.005)
    exp_drain = coordinator.drain_step_boundary_interjections(session_id, config=expired_cfg)
    assert exp_drain.interjection_applied is False
    assert exp_dir.status == InterventionStatus.EXPIRED


def test_capacity_limits_and_session_clearing() -> None:
    """Verifies bounded buffer limits, eviction, and session cleanup."""
    custom_cfg = DualTrackInterventionConfig(
        max_pending_interjections=2,
        max_preemption_queue_depth=2,
    )
    coordinator = DualTrackInterventionCoordinator(default_config=custom_cfg)
    session_id = "session_capacity_delta"

    # Submit 3 interjections to a buffer of max 2
    d1 = coordinator.submit_intervention(session_id, InterventionTrack.IMMEDIATE_INTERJECT, "Item 1", priority=10)
    d2 = coordinator.submit_intervention(session_id, InterventionTrack.IMMEDIATE_INTERJECT, "Item 2", priority=50)
    d3 = coordinator.submit_intervention(session_id, InterventionTrack.IMMEDIATE_INTERJECT, "Item 3", priority=100)

    # Lowest priority d1 should have been evicted and marked EXPIRED
    assert d1.status == InterventionStatus.EXPIRED

    drain_res = coordinator.drain_step_boundary_interjections(session_id)
    assert drain_res.consumed_directive_ids == [d3.directive_id, d2.directive_id]

    # Test clear_session
    coordinator.submit_intervention(session_id, InterventionTrack.QUEUE_PREEMPTION, "Pending queue task")
    assert coordinator.get_preemption_queue_snapshot(session_id).queue_length == 1

    coordinator.clear_session(session_id)
    assert coordinator.get_preemption_queue_snapshot(session_id).queue_length == 0
