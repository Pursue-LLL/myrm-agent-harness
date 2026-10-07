"""Cost-aware batch task scheduler for peak/off-peak economic arbitrage.

[INPUT]
Submitted background batch tasks, provider billing rules, and real-time/mock UTC timestamps.

[OUTPUT]
Opportunistic scheduling decisions, delayed dispatch queues, and quantifiable cost dividends.

[POS]
Item 122 in topic_06 roadmap: exploits 1/60 cost multiplier in off-peak LLM provider windows.
"""

import threading
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.runtime.context.batch_task_cost_scheduler_types import (
    BatchTaskDescriptor,
    CostTimeWindowKind,
    ProviderTimeWindowRule,
    SchedulerDispatchDecision,
    SchedulerQueueMetrics,
    TaskCostUrgencyPolicy,
)


class PeakOffPeakCostScheduler:
    """Manages batch task queues and schedules executions against provider pricing tiers."""

    def __init__(
        self,
        custom_rules: Sequence[ProviderTimeWindowRule] = (),
    ) -> None:
        self._lock = threading.RLock()
        self._rules: dict[str, ProviderTimeWindowRule] = {}
        self._pending_tasks: dict[str, BatchTaskDescriptor] = {}

        self._bootstrap_default_rules()
        for rule in custom_rules:
            self._rules[rule.provider_id] = rule

    def _bootstrap_default_rules(self) -> None:
        """Seed default tariff rules benchmarked against DeepSeek off-peak window."""
        # DeepSeek official off-peak: 00:30 - 08:30 UTC+8 (which corresponds to 16:30 - 00:30 UTC)
        # 16:30 UTC = 16 * 60 + 30 = 990 minutes
        # 00:30 UTC = 0 * 60 + 30 = 30 minutes
        deepseek_rule = ProviderTimeWindowRule(
            provider_id="deepseek",
            off_peak_start_minute_utc=990,
            off_peak_end_minute_utc=30,
            peak_uncached_price_per_m=3.00,
            off_peak_cached_price_per_m=0.05,
            description="DeepSeek V3/V4 off-peak: 00:30-08:30 UTC+8 (16:30-00:30 UTC) with 60x maximum price dividend",
        )
        self._rules["deepseek"] = deepseek_rule

    def register_provider_rule(self, rule: ProviderTimeWindowRule) -> None:
        """Register or update provider time window rule."""
        with self._lock:
            self._rules[rule.provider_id] = rule

    def is_in_off_peak(self, provider_id: str, dt_utc: datetime) -> bool:
        """Determine whether the specified UTC time falls within the provider's off-peak window."""
        with self._lock:
            rule = self._rules.get(provider_id)
            if not rule:
                return False

            cur_minute = dt_utc.hour * 60 + dt_utc.minute
            start_m = rule.off_peak_start_minute_utc
            end_m = rule.off_peak_end_minute_utc

            if start_m <= end_m:
                # Same-day interval (e.g., 100 to 500)
                return start_m <= cur_minute < end_m
            # Overnight interval spanning midnight (e.g., 990 to 30)
            return cur_minute >= start_m or cur_minute < end_m

    def calculate_delay_until_next_off_peak(
        self, provider_id: str, dt_utc: datetime
    ) -> int:
        """Calculate seconds remaining until the next off-peak window begins."""
        with self._lock:
            rule = self._rules.get(provider_id)
            if not rule:
                return 0

            if self.is_in_off_peak(provider_id, dt_utc):
                return 0

            cur_minute = dt_utc.hour * 60 + dt_utc.minute
            start_m = rule.off_peak_start_minute_utc

            if cur_minute < start_m:
                minutes_wait = start_m - cur_minute
            else:
                minutes_wait = (1440 - cur_minute) + start_m

            # Subtract current seconds within minute to be exact
            return max(0, minutes_wait * 60 - dt_utc.second)

    def evaluate_dispatch(
        self, task: BatchTaskDescriptor, now_utc: datetime | None = None
    ) -> SchedulerDispatchDecision:
        """Evaluate whether a task should execute immediately or be deferred."""
        effective_now = now_utc if now_utc is not None else datetime.now(UTC)
        provider = task.target_provider
        rule = self._rules.get(provider)
        multiplier = rule.max_savings_multiplier if rule else 1.0

        in_off_peak = self.is_in_off_peak(provider, effective_now)
        current_window = CostTimeWindowKind.OFF_PEAK if in_off_peak else CostTimeWindowKind.PEAK

        # 1. Interactive urgent tasks bypass off-peak waiting
        if task.urgency_policy == TaskCostUrgencyPolicy.REALTIME_INTERACTIVE:
            return SchedulerDispatchDecision(
                task_id=task.task_id,
                should_execute_now=True,
                current_window=current_window,
                delay_seconds=0,
                reason="Interactive task requires immediate dispatch",
                savings_multiplier_estimate=1.0,
            )

        # 2. If already in off-peak, execute immediately with max savings
        if in_off_peak:
            return SchedulerDispatchDecision(
                task_id=task.task_id,
                should_execute_now=True,
                current_window=CostTimeWindowKind.OFF_PEAK,
                delay_seconds=0,
                reason=f"Dispatched during off-peak window with ~{multiplier:.1f}x cost dividend",
                savings_multiplier_estimate=multiplier,
            )

        # 3. In peak window: Near-realtime executes, opportunistic defers
        if task.urgency_policy == TaskCostUrgencyPolicy.NEAR_REALTIME:
            return SchedulerDispatchDecision(
                task_id=task.task_id,
                should_execute_now=True,
                current_window=CostTimeWindowKind.PEAK,
                delay_seconds=0,
                reason="Near-realtime task dispatches immediately despite peak rate",
                savings_multiplier_estimate=1.0,
            )

        # OFF_PEAK_OPPORTUNISTIC: Defer until window opens
        delay_sec = self.calculate_delay_until_next_off_peak(provider, effective_now)
        return SchedulerDispatchDecision(
            task_id=task.task_id,
            should_execute_now=False,
            current_window=CostTimeWindowKind.PEAK,
            delay_seconds=delay_sec,
            reason=(
                f"Opportunistic task deferred for {delay_sec}s until off-peak window "
                f"to capture ~{multiplier:.1f}x discount"
            ),
            savings_multiplier_estimate=multiplier,
        )

    def enqueue_task(
        self, task: BatchTaskDescriptor, now_utc: datetime | None = None
    ) -> SchedulerDispatchDecision:
        """Evaluate task dispatch and store in queue if deferred."""
        with self._lock:
            decision = self.evaluate_dispatch(task, now_utc=now_utc)
            if not decision.should_execute_now:
                self._pending_tasks[task.task_id] = task
            return decision

    def drain_eligible_tasks(
        self, now_utc: datetime | None = None
    ) -> tuple[BatchTaskDescriptor, ...]:
        """Release all pending tasks that have become eligible for execution."""
        effective_now = now_utc if now_utc is not None else datetime.now(UTC)
        with self._lock:
            eligible: list[BatchTaskDescriptor] = []
            remaining: dict[str, BatchTaskDescriptor] = {}

            for task_id, task in self._pending_tasks.items():
                decision = self.evaluate_dispatch(task, now_utc=effective_now)
                if decision.should_execute_now:
                    eligible.append(task)
                else:
                    remaining[task_id] = task

            self._pending_tasks = remaining
            return tuple(eligible)

    def get_metrics(self, now_utc: datetime | None = None) -> SchedulerQueueMetrics:
        """Produce telemetry snapshot of queued tasks and accrued savings."""
        effective_now = now_utc if now_utc is not None else datetime.now(UTC)
        with self._lock:
            total_tokens = sum(t.estimated_tokens for t in self._pending_tasks.values())
            # Use deepseek as canonical reference for window classification
            in_off_peak = self.is_in_off_peak("deepseek", effective_now)
            current_window = CostTimeWindowKind.OFF_PEAK if in_off_peak else CostTimeWindowKind.PEAK

            # Calculate theoretical savings on queued tasks (peak 3.0 vs off_peak 0.05)
            # Diff is 2.95 per million tokens
            saved_estimate = (total_tokens / 1_000_000.0) * (3.00 - 0.05)

            return SchedulerQueueMetrics(
                queued_task_count=len(self._pending_tasks),
                deferred_token_count=total_tokens,
                current_window=current_window,
                estimated_saved_cost_usd_or_cny=saved_estimate,
            )
