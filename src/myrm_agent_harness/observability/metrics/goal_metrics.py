"""Goal lifecycle Prometheus metrics.

[INPUT]
- observability.metrics::create_counter, create_histogram (POS: Harness-layer generic metrics utilities)

[OUTPUT]
- Counters for goal state transitions (created, completed, budget_limited, paused, cancelled, resumed)
- Histograms for goal resource consumption (duration, tokens, cost)

[POS]
Harness-layer goal monitoring metrics. Records are made by GoalManager at
state transition points. prometheus_client graceful degradation is handled
by the create_counter/create_histogram utilities.
"""

from __future__ import annotations

from myrm_agent_harness.observability.metrics import (
    create_counter,
    create_histogram,
)

goal_created_total = create_counter(
    "goal_created_total",
    "Total number of goals created",
    (),
)

goal_completed_total = create_counter(
    "goal_completed_total",
    "Total number of goals that reached COMPLETE status",
    (),
)

goal_budget_limited_total = create_counter(
    "goal_budget_limited_total",
    "Total number of goals that hit budget limits",
    (),
)

goal_paused_total = create_counter(
    "goal_paused_total",
    "Total number of goals paused by zero-progress suppression",
    (),
)

goal_cancelled_total = create_counter(
    "goal_cancelled_total",
    "Total number of goals cancelled by the user",
    (),
)

goal_resumed_total = create_counter(
    "goal_resumed_total",
    "Total number of goal resume operations",
    (),
)

goal_objective_updated_total = create_counter(
    "goal_objective_updated_total",
    "Total number of goal objective runtime edits",
    (),
)

goal_duration_seconds = create_histogram(
    "goal_duration_seconds",
    "Goal execution wall-clock duration from creation to terminal state",
    ("status",),
    buckets=(5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)

goal_token_usage = create_histogram(
    "goal_token_usage_total",
    "Total tokens consumed by a goal at terminal state",
    ("status",),
    buckets=(500, 2000, 5000, 10000, 25000, 50000, 100000, 250000, 500000),
)

goal_cost_usd = create_histogram(
    "goal_cost_usd_total",
    "Total USD cost of a goal at terminal state",
    ("status",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

_STATUS_COUNTERS = {
    "complete": goal_completed_total,
    "budget_limited": goal_budget_limited_total,
    "paused": goal_paused_total,
    "cancelled": goal_cancelled_total,
}


def record_goal_created() -> None:
    """Record a goal creation event."""
    if goal_created_total is not None:
        goal_created_total.inc()


def record_goal_resumed() -> None:
    """Record a goal resume event."""
    if goal_resumed_total is not None:
        goal_resumed_total.inc()


def record_goal_objective_updated() -> None:
    """Record a goal objective runtime edit event."""
    if goal_objective_updated_total is not None:
        goal_objective_updated_total.inc()


_HISTOGRAM_STATES = {"complete", "budget_limited", "cancelled"}


def record_goal_terminal(status: str, duration_s: float, tokens: int, cost_usd: float) -> None:
    """Record metrics when a goal reaches a terminal or significant state.

    Histograms are only recorded for true terminal states (complete/budget_limited/cancelled),
    not for paused — which can be resumed, causing double-counting.
    """
    counter = _STATUS_COUNTERS.get(status)
    if counter is not None:
        counter.inc()
    if status not in _HISTOGRAM_STATES:
        return
    if goal_duration_seconds is not None and duration_s > 0:
        goal_duration_seconds.labels(status=status).observe(duration_s)
    if goal_token_usage is not None and tokens > 0:
        goal_token_usage.labels(status=status).observe(tokens)
    if goal_cost_usd is not None and cost_usd > 0:
        goal_cost_usd.labels(status=status).observe(cost_usd)
