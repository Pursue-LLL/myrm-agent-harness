"""Unit tests for Live Pre-Flight Budget Chokepoint Suite."""

import threading

import pytest

from myrm_agent_harness.core.security.pre_flight_budget import (
    BudgetAction,
    BudgetBroadcastBus,
    BudgetBroadcastEvent,
    BudgetEventType,
    BudgetExceededViolationError,
    BudgetPeriod,
    LiveBudgetStore,
    PreFlightBudgetChokepoint,
)


def test_no_budget_configured_pass_through() -> None:
    chokepoint = PreFlightBudgetChokepoint()
    decision = chokepoint.evaluate("proj_default")
    assert not decision.tripped
    assert decision.limit == 0.0

    # enforce passes without error
    passed = chokepoint.enforce_pre_flight("proj_default")
    assert not passed.tripped
    assert chokepoint.is_queue_dispatch_allowed("proj_default")


def test_budget_within_limit_and_spend_recording() -> None:
    store = LiveBudgetStore()
    bus = BudgetBroadcastBus()
    chokepoint = PreFlightBudgetChokepoint(store=store, bus=bus)

    events: list[BudgetBroadcastEvent] = []
    bus.subscribe_sync(events.append)

    store.set_config(
        project_id="proj_alpha",
        limit_amount=10.0,
        currency="USD",
        period=BudgetPeriod.DAILY,
        action=BudgetAction.PAUSE,
    )

    chokepoint.record_spend("proj_alpha", amount=3.5, model_name="gpt-4o")
    decision = chokepoint.evaluate("proj_alpha")
    assert not decision.tripped
    assert decision.current_spend == 3.5
    assert decision.limit == 10.0

    assert chokepoint.is_queue_dispatch_allowed("proj_alpha")
    assert len(events) == 1
    assert events[0].event_type == BudgetEventType.SPEND_RECORDED


def test_budget_exceeded_trips_hard_gate() -> None:
    store = LiveBudgetStore()
    bus = BudgetBroadcastBus()
    chokepoint = PreFlightBudgetChokepoint(store=store, bus=bus)

    tripped_events: list[BudgetBroadcastEvent] = []
    bus.subscribe_sync(tripped_events.append)

    store.set_config(
        project_id="proj_beta",
        limit_amount=5.0,
        currency="USD",
        period=BudgetPeriod.DAILY,
        action=BudgetAction.STOP,
    )

    chokepoint.record_spend("proj_beta", amount=4.0)
    # 4.0 < 5.0 -> passes
    chokepoint.enforce_pre_flight("proj_beta")

    # Record more spend to exceed limit
    chokepoint.record_spend("proj_beta", amount=1.5)
    # 5.5 >= 5.0 -> must trip
    decision = chokepoint.evaluate("proj_beta")
    assert decision.tripped
    assert decision.current_spend == 5.5
    assert decision.action == BudgetAction.STOP

    with pytest.raises(BudgetExceededViolationError) as exc_info:
        chokepoint.enforce_pre_flight("proj_beta")

    assert exc_info.value.decision.tripped
    assert exc_info.value.decision.current_spend == 5.5

    # Check queue dispatch locked
    assert not chokepoint.is_queue_dispatch_allowed("proj_beta")

    event_types = [e.event_type for e in tripped_events]
    assert BudgetEventType.CHOKEPOINT_TRIPPED in event_types
    assert BudgetEventType.QUEUE_LOCKED in event_types


def test_live_resolution_mid_session_reduction() -> None:
    """Validate that lowering budget mid-session immediately halts subsequent calls.

    Guarantees no stale session-start snapshot is used.
    """
    store = LiveBudgetStore()
    chokepoint = PreFlightBudgetChokepoint(store=store)

    store.set_config(
        project_id="proj_live",
        limit_amount=50.0,
        currency="USD",
        period=BudgetPeriod.DAILY,
    )

    chokepoint.record_spend("proj_live", amount=12.0)
    # Current spend is 12.0, under 50.0 limit -> passes
    chokepoint.enforce_pre_flight("proj_live")

    # User lowers budget limit mid-session to 10.0
    store.set_config(
        project_id="proj_live",
        limit_amount=10.0,
        currency="USD",
        period=BudgetPeriod.DAILY,
    )

    # Live resolution must instantly trip!
    decision = chokepoint.evaluate("proj_live")
    assert decision.tripped
    assert decision.limit == 10.0
    assert decision.current_spend == 12.0

    with pytest.raises(BudgetExceededViolationError):
        chokepoint.enforce_pre_flight("proj_live")


def test_concurrent_spend_and_enforcement() -> None:
    store = LiveBudgetStore()
    chokepoint = PreFlightBudgetChokepoint(store=store)

    store.set_config(
        project_id="proj_concurrent",
        limit_amount=100.0,
        currency="USD",
        period=BudgetPeriod.TOTAL,
    )

    def worker() -> None:
        for _ in range(20):
            chokepoint.record_spend("proj_concurrent", amount=0.5)
            chokepoint.evaluate("proj_concurrent")

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    decision = chokepoint.evaluate("proj_concurrent")
    assert decision.current_spend == 50.0
    assert not decision.tripped
