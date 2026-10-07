"""[POS]: tests/unit/toolkits/memory/test_dialectic_guard_suite.py
[INPUT]: DialecticLivenessStateMachine and related configs.
[OUTPUT]: Pytest test cases verifying timeout recovery, token orphan rejection, stale pivot discard, and exponential backoff.
"""

from myrm_agent_harness.toolkits.memory import (
    DialecticLivenessConfig,
    DialecticLivenessStateMachine,
    ExecutionSlotState,
)


def test_hung_thread_timeout_sweep_and_recovery() -> None:
    """Validate hung threads are marked dead after 2x timeout and new slots can trigger."""
    config = DialecticLivenessConfig(
        base_cadence=5,
        timeout_seconds=30.0,
        stale_thread_multiplier=2.0,
    )
    sm = DialecticLivenessStateMachine(config)
    session_id = "sess_liveness_01"

    # Turn 5: Triggers first cycle at t=100.0s
    triggered, token1 = sm.should_trigger(session_id, current_turn=5, now_mono=100.0)
    assert triggered is True
    assert token1 == 1

    # At t=140.0s (40s elapsed, within 60s stale limit): Not dead yet, cannot trigger duplicate
    triggered_mid, token_mid = sm.should_trigger(session_id, current_turn=6, now_mono=140.0)
    assert triggered_mid is False
    assert token_mid is None

    # At t=165.0s (65s elapsed > 30s * 2 = 60s): Dead thread detected!
    # Turn 10: Cadence requirement met (10 - 5 = 5 >= 5)
    triggered_new, token2 = sm.should_trigger(session_id, current_turn=10, now_mono=165.0)
    assert triggered_new is True
    assert token2 == 2

    telemetry = sm.get_telemetry(session_id, current_turn=10)
    assert telemetry.dead_threads_recovered == 1
    assert telemetry.active_cycle_token == 2
    assert telemetry.slot_state == ExecutionSlotState.RUNNING.value


def test_orphan_zombie_token_rejection() -> None:
    """Validate late return with superseded cycle token is rejected to prevent dirty writes."""
    config = DialecticLivenessConfig(base_cadence=5, timeout_seconds=10.0, stale_thread_multiplier=2.0)
    sm = DialecticLivenessStateMachine(config)
    session_id = "sess_orphan_02"

    # Start cycle with token 1
    _, token1 = sm.should_trigger(session_id, current_turn=5, now_mono=10.0)
    assert token1 == 1

    # Simulate thread hung past stale limit (35s > 20s) and next cycle triggered with token 2
    _, token2 = sm.should_trigger(session_id, current_turn=10, now_mono=35.0)
    assert token2 == 2

    # Late result arrives from zombie thread with token 1
    accepted_stale = sm.submit_result(
        session_id=session_id,
        cycle_token=token1,
        content="Late arriving dialectic conclusions",
        now_mono=40.0,
    )
    assert accepted_stale is False

    telemetry = sm.get_telemetry(session_id, current_turn=10)
    assert telemetry.stale_tokens_rejected == 1

    # Now result arrives from current active cycle with token 2
    accepted_valid = sm.submit_result(
        session_id=session_id,
        cycle_token=token2,
        content="Current fresh dialectic conclusions",
        now_mono=42.0,
    )
    assert accepted_valid is True


def test_stale_conversational_pivot_discard() -> None:
    """Validate pending result is discarded when user conversation moves past stale limit turns."""
    config = DialecticLivenessConfig(
        base_cadence=5,
        stale_result_multiplier=2.0,  # Limit is 5 * 2 = 10 turns
    )
    sm = DialecticLivenessStateMachine(config)
    session_id = "sess_pivot_03"

    # Fired at turn 5, completed at turn 5
    sm.should_trigger(session_id, current_turn=5, now_mono=10.0)
    sm.submit_result(session_id, cycle_token=1, content="Topic A: Docker network", now_mono=15.0)

    # User conversation rapidly pivots to turn 16 (delta_turns = 16 - 5 = 11 > 10)
    consumed_result = sm.consume_pending_result(session_id, current_turn=16)
    assert consumed_result is None  # Discarded!

    telemetry = sm.get_telemetry(session_id, current_turn=16)
    assert telemetry.stale_pivots_discarded == 1


def test_empty_streak_backoff_and_fresh_consumption() -> None:
    """Validate empty returns trigger exponential backoff up to max_backoff_multiplier."""
    config = DialecticLivenessConfig(base_cadence=5, max_backoff_multiplier=4)
    sm = DialecticLivenessStateMachine(config)
    session_id = "sess_backoff_04"

    assert sm.get_effective_cadence(session_id) == 5

    # 1. First empty return -> streak 1 -> cadence = 5 * (1 + 1) = 10
    sm.should_trigger(session_id, current_turn=5, now_mono=10.0)
    sm.submit_result(session_id, cycle_token=1, content="", now_mono=12.0)
    assert sm.get_effective_cadence(session_id) == 10

    # 2. Second empty return -> streak 2 -> cadence = 5 * (1 + 2) = 15
    sm.should_trigger(session_id, current_turn=15, now_mono=20.0)
    sm.submit_result(session_id, cycle_token=2, content="   \n", now_mono=22.0)
    assert sm.get_effective_cadence(session_id) == 15

    # 3. Third return with content -> staged -> consumed -> streak resets to 0
    sm.should_trigger(session_id, current_turn=30, now_mono=30.0)
    sm.submit_result(session_id, cycle_token=3, content="Valid conclusions", now_mono=32.0)
    res = sm.consume_pending_result(session_id, current_turn=31)
    assert res == "Valid conclusions"
    assert sm.get_effective_cadence(session_id) == 5


def test_mutation_wakeup_signal_resets_backoff() -> None:
    """Validate notify_critical_mutation immediately resets backoff to base cadence."""
    config = DialecticLivenessConfig(base_cadence=5, max_backoff_multiplier=6)
    sm = DialecticLivenessStateMachine(config)
    session_id = "sess_wakeup_05"

    # Build up empty streak of 3 -> cadence = 5 * 4 = 20
    for i in range(1, 4):
        sm.should_trigger(session_id, current_turn=i * 20, now_mono=float(i * 10))
        sm.submit_result(session_id, cycle_token=i, content=None, now_mono=float(i * 10 + 2))

    assert sm.get_effective_cadence(session_id) == 20

    # Critical mutation event occurs (e.g., authoritative user rule agreed)
    sm.notify_critical_mutation(session_id, reason="New authoritative guideline agreed")
    assert sm.get_effective_cadence(session_id) == 5

    telemetry = sm.get_telemetry(session_id, current_turn=70)
    assert telemetry.empty_streak == 0
    assert any(log.action == "mutation_wakeup_streak_reset" for log in telemetry.audit_events)
