"""Agent execution monitoring metrics.

Provides通用Agent执行监控指标，适用于任何使用Myrm框架的项目。

[INPUT]
- (none — pure metrics definition)

[OUTPUT]
- agent_run_total — Total agent runs counter
- agent_run_failed_total — Agent failures counter
- agent_run_duration_seconds — Agent duration histogram
- time_to_first_action_seconds — TTFA histogram
- tool_execution_total — Tool execution counter
- tool_execution_failed_total — Tool failure counter

[POS]
Harness-layer generic Agent monitoring metrics reusable by any Myrm-based project.

"""

from __future__ import annotations

from myrm_agent_harness.observability.metrics import (
    create_counter,
    create_histogram,
)

# Agent execution counters
agent_run_total = create_counter(
    "agent_run_total",
    "Total number of agent runs",
    ("agent_type",),
)

agent_run_failed_total = create_counter(
    "agent_run_failed_total",
    "Total number of agent run failures",
    ("agent_type", "error_type"),
)

# Agent execution duration
agent_run_duration_seconds = create_histogram(
    "agent_run_duration_seconds",
    "Agent run duration in seconds",
    ("agent_type",),
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)

time_to_first_action_seconds = create_histogram(
    "time_to_first_action_seconds",
    "Time from agent start to the first tool execution in seconds (TTFA)",
    ("agent_type",),
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)

import time
from contextvars import ContextVar

_ttfa_start_time: ContextVar[float | None] = ContextVar("ttfa_start_time", default=None)


def record_ttfa_run_start() -> None:
    """Record the start time of an agent run for TTFA calculation."""
    _ttfa_start_time.set(time.time())


def record_ttfa_first_action(agent_type: str = "unknown") -> None:
    """Record the Time-To-First-Action (TTFA) if this is the first tool call of the run."""
    try:
        start_time = _ttfa_start_time.get()
        if start_time is not None:
            ttfa = time.time() - start_time
            if time_to_first_action_seconds is not None:
                time_to_first_action_seconds.labels(agent_type=agent_type).observe(ttfa)
            # Clear to ensure we only record the FIRST action
            _ttfa_start_time.set(None)
    except LookupError:
        pass
    except Exception:
        pass


tool_execution_total = create_counter(
    "tool_execution_total",
    "Total number of tool executions",
    ("tool_name",),
)

tool_execution_failed_total = create_counter(
    "tool_execution_failed_total",
    "Total number of tool execution failures",
    ("tool_name", "error_type"),
)


__all__ = [
    "agent_run_duration_seconds",
    "agent_run_failed_total",
    "agent_run_total",
    "time_to_first_action_seconds",
    "tool_execution_failed_total",
    "tool_execution_total",
]
