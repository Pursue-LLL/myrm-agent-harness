"""Comprehensive unit tests for Adaptive Wakeup Driver in Harness framework.

Validates bounded consecutive wakes, host activity routing (inject vs followup),
human reset, and user stop suppression.
"""

from myrm_agent_harness.agent.coordination.adaptive_wakeup import (
    AdaptiveWakeupRouter,
    HostActivityState,
    WakeupBudgetTracker,
    WakeupChannel,
    WakeupEvent,
    WakeupSourceType,
)


def test_budget_tracker_exhaustion_and_human_reset() -> None:
    """Validate that consecutive wakes are strictly bounded and reset by human turns."""
    tracker = WakeupBudgetTracker(default_max_consecutive_wakes=3)
    session_id = "test-session-budget"

    # Initially 3 wakes available
    state = tracker.get_budget_state(session_id)
    assert state.consecutive_wakes == 0
    assert state.budget_remaining == 3
    assert not state.is_exhausted

    # Consume 3 times
    assert tracker.consume_wake_budget(session_id) is True
    assert tracker.consume_wake_budget(session_id) is True
    assert tracker.consume_wake_budget(session_id) is True

    # 4th time should be rejected
    assert tracker.consume_wake_budget(session_id) is False
    state_exhausted = tracker.get_budget_state(session_id)
    assert state_exhausted.consecutive_wakes == 3
    assert state_exhausted.budget_remaining == 0
    assert state_exhausted.is_exhausted is True

    # Human message resets budget
    reset_state = tracker.record_human_turn(session_id)
    assert reset_state.consecutive_wakes == 0
    assert reset_state.budget_remaining == 3
    assert reset_state.last_human_reset_time is not None

    # Now consumption succeeds again
    assert tracker.consume_wake_budget(session_id) is True


def test_budget_tracker_user_stop_suppression() -> None:
    """Validate that user stop request suppresses consumption even with budget remaining."""
    tracker = WakeupBudgetTracker(default_max_consecutive_wakes=3)
    session_id = "test-session-stop"

    tracker.record_user_stop(session_id)
    state = tracker.get_budget_state(session_id)
    assert state.is_user_stopped is True

    # Consumption must fail immediately
    assert tracker.consume_wake_budget(session_id) is False

    # Human turn clears stop state and resets budget
    tracker.record_human_turn(session_id)
    assert tracker.get_budget_state(session_id).is_user_stopped is False
    assert tracker.consume_wake_budget(session_id) is True


def test_router_busy_host_injection() -> None:
    """Validate that when host is BUSY, settlements are injected into in-flight queue."""
    router = AdaptiveWakeupRouter(default_max_consecutive_wakes=3)
    session_id = "test-session-busy"

    router.set_host_activity(session_id, HostActivityState.BUSY)
    assert router.get_host_activity(session_id) == HostActivityState.BUSY

    event = WakeupEvent(
        source_type=WakeupSourceType.BACKGROUND_JOB,
        source_id="job-101",
        session_id=session_id,
        success=True,
        summary="Background build completed",
    )

    decision = router.route(event)
    assert decision.channel == WakeupChannel.INJECT
    assert "in-flight" in decision.reason
    assert decision.consecutive_wakes == 0

    # Injected event must be in queue
    queued = router.peek_injected_events(session_id)
    assert len(queued) == 1
    assert queued[0].source_id == "job-101"

    # Atomic drain
    drained = router.drain_injected_events(session_id)
    assert len(drained) == 1
    assert drained[0].source_id == "job-101"
    assert len(router.peek_injected_events(session_id)) == 0


def test_router_idle_host_followup_and_degradation() -> None:
    """Validate that idle host gets FOLLOWUP until budget reaches max, then DEGRADE."""
    router = AdaptiveWakeupRouter(default_max_consecutive_wakes=2)
    session_id = "test-session-idle"

    event_subagent = WakeupEvent(
        source_type=WakeupSourceType.SUBAGENT,
        source_id="subagent-task-1",
        session_id=session_id,
        success=True,
        summary="Subagent code review finished",
    )

    # 1st wake -> FOLLOWUP
    d1 = router.route(event_subagent)
    assert d1.channel == WakeupChannel.FOLLOWUP
    assert d1.consecutive_wakes == 1
    assert d1.budget_remaining == 1

    # 2nd wake -> FOLLOWUP
    d2 = router.route(event_subagent)
    assert d2.channel == WakeupChannel.FOLLOWUP
    assert d2.consecutive_wakes == 2
    assert d2.budget_remaining == 0

    # 3rd wake -> DEGRADE (budget exhausted)
    d3 = router.route(event_subagent)
    assert d3.channel == WakeupChannel.DEGRADE
    assert "degraded" in d3.reason.lower()
    assert d3.consecutive_wakes == 2
    assert d3.budget_remaining == 0

    # Degraded event must be staged in inbox for human pickup
    staged = router.drain_injected_events(session_id)
    assert len(staged) == 1
    assert staged[0].source_id == "subagent-task-1"


def test_router_user_stop_suppresses_wakeup() -> None:
    """Validate that user stop flag suppresses any followup or injection."""
    router = AdaptiveWakeupRouter(default_max_consecutive_wakes=3)
    session_id = "test-session-suppress"

    router.record_user_stop(session_id)

    event = WakeupEvent(
        source_type=WakeupSourceType.BACKGROUND_JOB,
        source_id="job-aborted",
        session_id=session_id,
        success=False,
        summary="Job aborted after timeout",
    )

    decision = router.route(event)
    assert decision.channel == WakeupChannel.SUPPRESS
    assert "suppressed" in decision.reason.lower()
    assert len(router.peek_injected_events(session_id)) == 0


def test_router_session_reset() -> None:
    """Validate complete reset of host state, budget, and inbox."""
    router = AdaptiveWakeupRouter(default_max_consecutive_wakes=3)
    session_id = "test-session-reset"

    router.set_host_activity(session_id, HostActivityState.BUSY)
    event = WakeupEvent(
        source_type=WakeupSourceType.SUBAGENT,
        source_id="sub-1",
        session_id=session_id,
        success=True,
        summary="Done",
    )
    router.route(event)
    assert len(router.peek_injected_events(session_id)) == 1

    router.reset_session(session_id)
    assert router.get_host_activity(session_id) == HostActivityState.IDLE
    assert len(router.peek_injected_events(session_id)) == 0
    assert router.budget_tracker.get_budget_state(session_id).consecutive_wakes == 0
