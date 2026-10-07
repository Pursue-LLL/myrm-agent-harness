"""Unit tests for PeakOffPeakCostScheduler and batch economic arbitrage.

[INPUT]
Simulated peak/off-peak UTC timestamps, diverse task urgency levels, and provider tariff configurations.

[OUTPUT]
Verification of immediate vs deferred dispatch, countdown accuracy, queue draining,
and thread safety.

[POS]
Quality gate for Item 122 in topic_06 roadmap.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from myrm_agent_harness.runtime.context.batch_task_cost_scheduler import (
    PeakOffPeakCostScheduler,
)
from myrm_agent_harness.runtime.context.batch_task_cost_scheduler_types import (
    BatchTaskDescriptor,
    CostTimeWindowKind,
    ProviderTimeWindowRule,
    TaskCostUrgencyPolicy,
    TaskPayloadKind,
)


def test_default_deepseek_rule_and_window_classification() -> None:
    scheduler = PeakOffPeakCostScheduler()

    # 18:00 UTC = 02:00 UTC+8 (inside off-peak window 00:30-08:30 UTC+8)
    dt_off_peak = datetime(2026, 10, 7, 18, 0, 0, tzinfo=UTC)
    assert scheduler.is_in_off_peak("deepseek", dt_off_peak) is True
    assert scheduler.calculate_delay_until_next_off_peak("deepseek", dt_off_peak) == 0

    # 05:00 UTC = 13:00 UTC+8 (inside peak window)
    dt_peak = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)
    assert scheduler.is_in_off_peak("deepseek", dt_peak) is False

    delay = scheduler.calculate_delay_until_next_off_peak("deepseek", dt_peak)
    # Next off-peak starts at 16:30 UTC (990 mins). 5:00 UTC is 300 mins. Diff is 690 mins = 41400 seconds.
    assert delay == 41400


def test_interactive_task_immediate_dispatch() -> None:
    scheduler = PeakOffPeakCostScheduler()
    task = BatchTaskDescriptor(
        task_id="task_interactive",
        payload_kind=TaskPayloadKind.OFFLINE_BATCH,
        urgency_policy=TaskCostUrgencyPolicy.REALTIME_INTERACTIVE,
    )

    # In peak window (05:00 UTC)
    dt_peak = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)
    decision = scheduler.evaluate_dispatch(task, now_utc=dt_peak)
    assert decision.should_execute_now is True
    assert decision.delay_seconds == 0
    assert "Interactive task" in decision.reason


def test_off_peak_opportunistic_task_deferral_during_peak() -> None:
    scheduler = PeakOffPeakCostScheduler()
    task = BatchTaskDescriptor(
        task_id="task_eval",
        payload_kind=TaskPayloadKind.EVAL_RUN,
        urgency_policy=TaskCostUrgencyPolicy.OFF_PEAK_OPPORTUNISTIC,
        estimated_tokens=500_000,
    )

    # In peak window (05:00 UTC)
    dt_peak = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)
    decision = scheduler.evaluate_dispatch(task, now_utc=dt_peak)
    assert decision.should_execute_now is False
    assert decision.current_window == CostTimeWindowKind.PEAK
    assert decision.delay_seconds == 41400
    assert decision.savings_multiplier_estimate == 60.0  # 3.00 / 0.05
    assert "Opportunistic task deferred" in decision.reason


def test_near_realtime_task_dispatch_during_peak() -> None:
    scheduler = PeakOffPeakCostScheduler()
    task = BatchTaskDescriptor(
        task_id="task_wiki_sync",
        payload_kind=TaskPayloadKind.WIKI_STALE_ARCHIVE,
        urgency_policy=TaskCostUrgencyPolicy.NEAR_REALTIME,
    )

    dt_peak = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)
    decision = scheduler.evaluate_dispatch(task, now_utc=dt_peak)
    assert decision.should_execute_now is True
    assert decision.delay_seconds == 0
    assert "Near-realtime task dispatches immediately" in decision.reason


def test_enqueue_and_drain_at_off_peak() -> None:
    scheduler = PeakOffPeakCostScheduler()
    dt_peak = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)

    task_opp1 = BatchTaskDescriptor(
        task_id="opp_1",
        payload_kind=TaskPayloadKind.MEMORY_CRYSTALLIZATION,
        urgency_policy=TaskCostUrgencyPolicy.OFF_PEAK_OPPORTUNISTIC,
        estimated_tokens=200_000,
    )
    task_opp2 = BatchTaskDescriptor(
        task_id="opp_2",
        payload_kind=TaskPayloadKind.WIKI_STALE_ARCHIVE,
        urgency_policy=TaskCostUrgencyPolicy.OFF_PEAK_OPPORTUNISTIC,
        estimated_tokens=300_000,
    )

    dec1 = scheduler.enqueue_task(task_opp1, now_utc=dt_peak)
    dec2 = scheduler.enqueue_task(task_opp2, now_utc=dt_peak)
    assert dec1.should_execute_now is False
    assert dec2.should_execute_now is False
    assert len(scheduler._pending_tasks) == 2

    # Still in peak -> draining releases 0 tasks
    assert len(scheduler.drain_eligible_tasks(now_utc=dt_peak)) == 0

    # Fast forward to off-peak (18:00 UTC)
    dt_off_peak = datetime(2026, 10, 7, 18, 0, 0, tzinfo=UTC)
    drained = scheduler.drain_eligible_tasks(now_utc=dt_off_peak)
    assert len(drained) == 2
    assert {t.task_id for t in drained} == {"opp_1", "opp_2"}
    assert len(scheduler._pending_tasks) == 0


def test_metrics_calculation() -> None:
    scheduler = PeakOffPeakCostScheduler()
    dt_peak = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)

    task = BatchTaskDescriptor(
        task_id="batch_large",
        payload_kind=TaskPayloadKind.OFFLINE_BATCH,
        urgency_policy=TaskCostUrgencyPolicy.OFF_PEAK_OPPORTUNISTIC,
        estimated_tokens=1_000_000,
    )
    scheduler.enqueue_task(task, now_utc=dt_peak)

    metrics = scheduler.get_metrics(now_utc=dt_peak)
    assert metrics.queued_task_count == 1
    assert metrics.deferred_token_count == 1_000_000
    assert metrics.current_window == CostTimeWindowKind.PEAK
    # 1M tokens saved: 3.00 - 0.05 = 2.95
    assert abs(metrics.estimated_saved_cost_usd_or_cny - 2.95) < 0.01


def test_custom_provider_rule_and_thread_safety() -> None:
    scheduler = PeakOffPeakCostScheduler()
    # Custom provider with same-day window: 02:00 to 06:00 UTC (120 to 360 mins)
    custom_rule = ProviderTimeWindowRule(
        provider_id="openai_batch",
        off_peak_start_minute_utc=120,
        off_peak_end_minute_utc=360,
        peak_uncached_price_per_m=5.00,
        off_peak_cached_price_per_m=0.25,
    )
    scheduler.register_provider_rule(custom_rule)
    assert custom_rule.max_savings_multiplier == 20.0

    def worker(worker_id: int) -> bool:
        t = BatchTaskDescriptor(
            task_id=f"thread_task_{worker_id}",
            payload_kind=TaskPayloadKind.OFFLINE_BATCH,
            urgency_policy=TaskCostUrgencyPolicy.OFF_PEAK_OPPORTUNISTIC,
            target_provider="openai_batch",
        )
        dec = scheduler.enqueue_task(t, now_utc=datetime(2026, 10, 7, 1, 0, 0, tzinfo=UTC))
        return dec.delay_seconds > 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(25)]
        results = [f.result() for f in futures]

    assert all(results)
    assert len(scheduler._pending_tasks) == 25
