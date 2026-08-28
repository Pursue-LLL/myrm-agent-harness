"""Friction Aggregator for cross-session statistical attribution and heatmap analytics.

[INPUT]
- myrm_agent_harness.observability.friction.types::(FrictionCategory, TaskFrictionEvent, FrictionSummary) (POS: 摩擦点类型系统)

[OUTPUT]
- FrictionAggregator: Aggregator for sliding-window and cross-session friction analytics

[POS]
Statistical aggregation engine computing friction distribution, top offending tools, and session severity.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Sequence

from myrm_agent_harness.observability.friction.types import (
    FrictionSummary,
    TaskFrictionEvent,
)


class FrictionAggregator:
    """Aggregates TaskFrictionEvents to identify high-frequency failure modes and offending tools."""

    def __init__(self) -> None:
        self._events: list[TaskFrictionEvent] = []

    def record(self, event: TaskFrictionEvent) -> None:
        """Append a single friction event."""
        self._events.append(event)

    def record_batch(self, events: Sequence[TaskFrictionEvent]) -> None:
        """Append a sequence of friction events."""
        self._events.extend(events)

    def clear(self) -> None:
        """Clear all stored friction events."""
        self._events.clear()

    @property
    def total_count(self) -> int:
        """Total number of recorded events."""
        return len(self._events)

    def summarize(self, *, top_tools_limit: int = 5) -> FrictionSummary:
        """Compute full statistical summary across recorded friction events."""
        if not self._events:
            return FrictionSummary(
                total_frictions=0,
                by_category={},
                by_tool={},
                by_fault_side={},
                top_frequent_tools=[],
                high_friction_sessions=[],
            )

        cat_counter: Counter[str] = Counter()
        tool_counter: Counter[str] = Counter()
        fault_counter: Counter[str] = Counter()
        session_counter: Counter[str] = Counter()

        for evt in self._events:
            cat_counter[evt.category.value] += 1
            tool_counter[evt.tool_name] += 1
            fault_counter[evt.fault_side] += 1
            session_counter[evt.session_id] += 1

        top_tools = tool_counter.most_common(top_tools_limit)
        # Sessions with >= 3 friction points classified as high friction
        high_fric_sessions = [sess for sess, count in session_counter.items() if count >= 3]

        return FrictionSummary(
            total_frictions=len(self._events),
            by_category=dict(cat_counter),
            by_tool=dict(tool_counter),
            by_fault_side=dict(fault_counter),
            top_frequent_tools=top_tools,
            high_friction_sessions=high_fric_sessions,
        )
