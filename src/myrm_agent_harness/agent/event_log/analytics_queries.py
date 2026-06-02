"""Read-side analytics helpers for ``EventLogger``.

Keeps ``logger.py`` focused on write-path lifecycle management while query
aggregation logic lives in a separate module.

[INPUT]
- (none)

[OUTPUT]
- get_tool_usage_stats: Query tool usage statistics for a single session.
- get_activity_patterns: Query per-hour activity patterns for a single session.
- get_bash_audit_logs: Query bash command audit logs for a single session.
- get_bash_execution_stats: Aggregate bash command execution statistics for a single ...
- get_session_summary: Aggregate session analytics with full tool/session_end co...

[POS]
Read-side analytics helpers for ``EventLogger``.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import AsyncIterable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from .types import (
    ActivityPatterns,
    BashExecutionStats,
    EventFilter,
    HourlyToolUsage,
    SessionAnalytics,
    SessionEvent,
    StructuredEvent,
    ToolBreakdown,
    ToolStabilityAnalytics,
    ToolStabilityDaily,
    ToolUsageStats,
)

if TYPE_CHECKING:
    from .protocols import EventLogBackend


async def get_tool_usage_stats(
    backend: EventLogBackend, session_id: str, *, time_range_seconds: float | None = None
) -> list[ToolUsageStats]:
    """Query tool usage statistics for a single session."""
    start_time = time.time() - time_range_seconds if time_range_seconds is not None else None
    event_filter = EventFilter(
        event_types=frozenset(
            {
                "tool_start",
                "tool_end",
                "tool_failure",
                "tool_cancelled",
                "tool_timeout",
                "tool_retry",
                "tool_token_usage",
            }
        ),
        start_time=start_time,
    )

    tool_data: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "total": 0,
            "success": 0,
            "failure": 0,
            "timeout": 0,
            "retry": 0,
            "durations": [],
            "failure_reasons": Counter(),
            "tokens": 0,
        }
    )

    for event in await _collect_events(backend.get_events(session_id, event_filter)):
        tool_name = event.data.get("tool_name")
        if not isinstance(tool_name, str):
            continue

        data = tool_data[tool_name]
        if event.event_type == "tool_start":
            data["total"] = cast(int, data["total"]) + 1
        elif event.event_type == "tool_end":
            data["success"] = cast(int, data["success"]) + 1
            duration_ms = event.data.get("duration_ms")
            if isinstance(duration_ms, (int, float)):
                _durations(data).append(float(duration_ms))
        elif event.event_type == "tool_failure":
            data["failure"] = cast(int, data["failure"]) + 1
            duration_ms = event.data.get("duration_ms")
            if isinstance(duration_ms, (int, float)):
                _durations(data).append(float(duration_ms))
            reason = event.data.get("error_code") or event.data.get("error") or "<no_error_info>"
            _failure_reasons(data)[str(reason if isinstance(reason, str) else type(reason).__name__)] += 1
        elif event.event_type == "tool_cancelled":
            duration_ms = event.data.get("duration_ms")
            if isinstance(duration_ms, (int, float)):
                _durations(data).append(float(duration_ms))
        elif event.event_type == "tool_timeout":
            data["timeout"] = cast(int, data["timeout"]) + 1
        elif event.event_type == "tool_retry":
            data["retry"] = cast(int, data["retry"]) + 1
        elif event.event_type == "tool_token_usage":
            tokens = event.data.get("tokens")
            if isinstance(tokens, (int, float)):
                data["tokens"] = cast(int, data["tokens"]) + int(tokens)

    results: list[ToolUsageStats] = []
    for tool_name, data in tool_data.items():
        durations = _durations(data)
        total_calls = cast(int, data["total"])
        total_tokens = cast(int, data["tokens"])
        avg_duration_ms = sum(durations) / len(durations) if durations else 0.0
        avg_tokens = float(total_tokens) / float(total_calls) if total_calls > 0 else 0.0
        results.append(
            ToolUsageStats(
                tool_name=tool_name,
                total_calls=total_calls,
                success_count=cast(int, data["success"]),
                failure_count=cast(int, data["failure"]),
                timeout_count=cast(int, data["timeout"]),
                retry_count=cast(int, data["retry"]),
                avg_duration_ms=avg_duration_ms,
                failure_reasons=dict(_failure_reasons(data)),
                total_tokens=total_tokens,
                avg_tokens=avg_tokens,
            )
        )

    results.sort(key=lambda item: item.total_calls, reverse=True)
    return results


async def get_activity_patterns(
    backend: EventLogBackend, session_id: str, *, time_range_seconds: float | None = None
) -> ActivityPatterns:
    """Query per-hour activity patterns for a single session."""
    start_time = time.time() - time_range_seconds if time_range_seconds is not None else None
    event_filter = EventFilter(
        event_types=frozenset({"tool_start", "tool_end", "tool_failure", "tool_cancelled"}), start_time=start_time
    )

    hourly_data: dict[tuple[int, str], dict[str, object]] = defaultdict(lambda: {"count": 0, "durations": []})
    for event in await _collect_events(backend.get_events(session_id, event_filter)):
        tool_name = event.data.get("tool_name")
        if not isinstance(tool_name, str):
            continue

        hour = datetime.fromtimestamp(event.timestamp).hour
        data = hourly_data[(hour, tool_name)]
        if event.event_type == "tool_start":
            data["count"] = cast(int, data["count"]) + 1

        if event.event_type in {"tool_end", "tool_failure", "tool_cancelled"}:
            duration_ms = event.data.get("duration_ms")
            if isinstance(duration_ms, (int, float)):
                _durations(data).append(float(duration_ms))

    hourly_breakdown: list[HourlyToolUsage] = []
    hour_totals: dict[int, int] = defaultdict(int)
    tool_totals: dict[str, int] = defaultdict(int)

    for (hour, tool_name), data in hourly_data.items():
        call_count = cast(int, data["count"])
        durations = _durations(data)
        avg_duration_ms = sum(durations) / len(durations) if durations else 0.0
        hourly_breakdown.append(
            HourlyToolUsage(hour=hour, tool_name=tool_name, call_count=call_count, avg_duration_ms=avg_duration_ms)
        )
        hour_totals[hour] += call_count
        tool_totals[tool_name] += call_count

    peak_hour = max(hour_totals, key=lambda k: hour_totals[k]) if hour_totals else 0
    peak_tool = max(tool_totals, key=lambda k: tool_totals[k]) if tool_totals else ""
    return ActivityPatterns(hourly_breakdown=hourly_breakdown, peak_hour=peak_hour, peak_tool=peak_tool)


async def get_bash_audit_logs(
    backend: EventLogBackend,
    session_id: str,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
    command_type: str | None = None,
    risk_level: str | None = None,
    limit: int = 100,
) -> list[StructuredEvent]:
    """Query bash command audit logs for a single session."""
    event_filter = EventFilter(
        event_types=frozenset({"bash_command_executed"}), start_time=start_time, end_time=end_time, limit=limit
    )

    results: list[StructuredEvent] = []
    for event in await _collect_events(backend.get_events(session_id, event_filter)):
        if command_type and event.data.get("command_type") != command_type:
            continue
        if risk_level and event.data.get("risk_level") != risk_level:
            continue
        results.append(event)

    results.sort(key=lambda item: item.timestamp, reverse=True)
    return results[:limit]


async def get_bash_execution_stats(backend: EventLogBackend, session_id: str) -> BashExecutionStats:
    """Aggregate bash command execution statistics for a single session."""
    event_filter = EventFilter(event_types=frozenset({"bash_command_executed"}))

    total = 0
    success_count = 0
    durations: list[float] = []
    error_counter: Counter[str] = Counter()
    command_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    hour_counter: Counter[int] = Counter()

    for event in await _collect_events(backend.get_events(session_id, event_filter)):
        total += 1
        success = bool(event.data.get("success"))
        if success:
            success_count += 1

        duration_ms = event.data.get("duration_ms")
        if isinstance(duration_ms, (int, float)):
            durations.append(float(duration_ms))

        if not success:
            error_msg = event.data.get("error_message", "<unknown>")
            if isinstance(error_msg, str):
                error_counter[error_msg[:100]] += 1

        command = event.data.get("command")
        if isinstance(command, str):
            command_counter[command[:50]] += 1

        command_type = event.data.get("command_type")
        if isinstance(command_type, str):
            type_counter[command_type] += 1

        hour_counter[datetime.fromtimestamp(event.timestamp).hour] += 1

    success_rate = (success_count / total) if total > 0 else 0.0
    avg_duration_ms = (sum(durations) / len(durations)) if durations else 0.0
    return BashExecutionStats(
        total_commands=total,
        success_rate=success_rate,
        avg_duration_ms=avg_duration_ms,
        error_top10=error_counter.most_common(10),
        command_hotmap=command_counter.most_common(10),
        type_distribution=dict(type_counter),
        hourly_breakdown=sorted(hour_counter.items()),
    )


async def get_session_summary(
    backend: EventLogBackend, session_id: str, *, events_limit: int = 150, timeline_limit: int = 100
) -> SessionAnalytics:
    """Aggregate session analytics with full tool/session_end coverage."""
    timeline_events = await _collect_events(backend.get_events(session_id, EventFilter(limit=events_limit)))
    tool_events = await _collect_events(
        backend.get_events(session_id, EventFilter(event_types=frozenset({"tool_start", "tool_end"})))
    )
    session_end_events = await _collect_events(
        backend.get_events(session_id, EventFilter(event_types=frozenset({"session_end"}), limit=1))
    )

    events_timeline = [
        SessionEvent(event_type=event.event_type, timestamp=event.timestamp, data=event.data)
        for event in timeline_events[:timeline_limit]
    ]

    duration_ms = 0.0
    task_metrics: dict[str, object] = {}
    token_economics: dict[str, object] | None = None
    if session_end_events:
        summary_data = session_end_events[0].data.get("summary", {})
        if isinstance(summary_data, dict):
            duration_ms = float(summary_data.get("duration_ms", 0))
            raw_task_metrics = summary_data.get("task_metrics")
            if isinstance(raw_task_metrics, dict):
                task_metrics = raw_task_metrics
            elif summary_data.get("compactions"):
                task_metrics = {"compression_count": int(summary_data.get("compactions", 0))}
            raw_token_economics = summary_data.get("token_economics")
            if isinstance(raw_token_economics, dict):
                token_economics = raw_token_economics

    tool_calls: dict[str, dict[str, Any]] = {}
    pending_starts: dict[str, int] = {}
    for event in tool_events:
        tool_name = event.data.get("tool_name")
        if not isinstance(tool_name, str):
            continue

        if event.event_type == "tool_start":
            bucket = tool_calls.setdefault(
                tool_name,
                {
                    "tool_name": tool_name,
                    "call_count": 0,
                    "total_duration_ms": 0.0,
                },
            )
            bucket["call_count"] = int(bucket["call_count"]) + 1
            pending_starts[tool_name] = pending_starts.get(tool_name, 0) + 1
        elif event.event_type == "tool_end" and tool_name in tool_calls:
            tool_calls[tool_name]["total_duration_ms"] = float(tool_calls[tool_name]["total_duration_ms"]) + float(
                event.data.get("duration_ms", 0)
            )
            if pending_starts.get(tool_name, 0) > 0:
                pending_starts[tool_name] -= 1

    tool_breakdown = [
        ToolBreakdown(
            tool_name=str(bucket["tool_name"]),
            call_count=int(bucket["call_count"]),
            total_duration_ms=float(bucket["total_duration_ms"]),
        )
        for bucket in tool_calls.values()
    ]
    return SessionAnalytics(
        session_id=session_id,
        duration_ms=duration_ms,
        tool_breakdown=tool_breakdown,
        events_timeline=events_timeline,
        task_metrics=task_metrics,
        token_economics=token_economics,
    )


async def get_global_tool_stability(
    backend: EventLogBackend, session_ids: list[str], *, tool_name: str | None = None, start_time: float | None = None
) -> ToolStabilityAnalytics:
    """Calculate global tool stability metrics aggregated by day across multiple sessions.

    Args:
        backend: The EventLogBackend instance
        session_ids: List of session IDs to query
        tool_name: Optional tool name to filter by. If None, aggregates all tools.
        start_time: Optional start time filter (UTC timestamp)
    """
    import asyncio
    import math
    from datetime import UTC, datetime

    event_filter = EventFilter(
        event_types=frozenset({"tool_start", "tool_end", "tool_failure", "tool_timeout"}), start_time=start_time
    )

    # Dictionary to aggregate metrics by (date, tool_name).
    daily_data: dict[tuple[str, str], dict[str, object]] = defaultdict(
        lambda: {
            "total": 0,
            "success": 0,
            "failure": 0,
            "timeout": 0,
            "durations": [],
            "reasons": Counter(),
        }
    )

    # Track overall busiest and most failed tool
    global_tool_totals: Counter[str] = Counter()
    global_tool_failures: Counter[str] = Counter()

    tasks = [backend.get_events(session_id, event_filter) for session_id in session_ids]
    all_session_events = await asyncio.gather(*tasks)

    for events in all_session_events:
        for event in await _collect_events(events):
            event_tool_name = event.data.get("tool_name")
            if not isinstance(event_tool_name, str):
                continue

            if tool_name and event_tool_name != tool_name:
                continue

            dt = datetime.fromtimestamp(event.timestamp, tz=UTC)
            date_str = dt.strftime("%Y-%m-%d")
            data = daily_data[(date_str, event_tool_name)]

            if event.event_type == "tool_start":
                data["total"] = cast(int, data["total"]) + 1
                global_tool_totals[event_tool_name] += 1
            elif event.event_type == "tool_end":
                data["success"] = cast(int, data["success"]) + 1
                duration_ms = event.data.get("duration_ms")
                if isinstance(duration_ms, (int, float)):
                    _durations(data).append(float(duration_ms))
            elif event.event_type == "tool_failure":
                data["failure"] = cast(int, data["failure"]) + 1
                global_tool_failures[event_tool_name] += 1
                duration_ms = event.data.get("duration_ms")
                if isinstance(duration_ms, (int, float)):
                    _durations(data).append(float(duration_ms))
                reason = event.data.get("error_code") or event.data.get("error") or "<unknown_failure>"
                _failure_reasons(data)[str(reason if isinstance(reason, str) else type(reason).__name__)] += 1
            elif event.event_type == "tool_timeout":
                data["timeout"] = cast(int, data["timeout"]) + 1
                global_tool_failures[event_tool_name] += 1
                _failure_reasons(data)["timeout"] += 1

    # Calculate global totals
    global_total_calls = sum(global_tool_totals.values())
    global_total_failures = sum(global_tool_failures.values())
    global_failure_rate = min(global_total_failures / global_total_calls, 1.0) if global_total_calls > 0 else 0.0

    busiest_tool = global_tool_totals.most_common(1)[0][0] if global_tool_totals else None
    most_failed_tool = global_tool_failures.most_common(1)[0][0] if global_tool_failures else None

    all_durations: list[float] = []

    # Build daily stability list (grouped by date + tool_name)
    daily_stability: list[ToolStabilityDaily] = []
    for (date_str, entry_tool_name) in sorted(daily_data.keys()):
        data = daily_data[(date_str, entry_tool_name)]

        total_calls = cast(int, data["total"])
        failure_count = cast(int, data["failure"])
        timeout_count = cast(int, data["timeout"])
        total_failures = failure_count + timeout_count

        durations = _durations(data)
        durations.sort()
        all_durations.extend(durations)

        avg_duration_ms = sum(durations) / len(durations) if durations else 0.0

        def get_percentile(arr: list[float], p: float) -> float:
            if not arr:
                return 0.0
            idx = math.ceil(p * len(arr)) - 1
            return arr[max(0, min(idx, len(arr) - 1))]

        p90_duration_ms = get_percentile(durations, 0.90)
        p99_duration_ms = get_percentile(durations, 0.99)
        failure_rate = min(total_failures / total_calls, 1.0) if total_calls > 0 else 0.0

        daily_stability.append(
            ToolStabilityDaily(
                date=date_str,
                tool_name=entry_tool_name,
                total_calls=total_calls,
                success_count=cast(int, data["success"]),
                failure_count=failure_count,
                timeout_count=timeout_count,
                avg_duration_ms=avg_duration_ms,
                p90_duration_ms=p90_duration_ms,
                p99_duration_ms=p99_duration_ms,
                failure_rate=failure_rate,
                failure_reasons=dict(_failure_reasons(data).most_common(10)),
            )
        )

    global_avg_duration_ms = sum(all_durations) / len(all_durations) if all_durations else 0.0

    return ToolStabilityAnalytics(
        daily_stability=daily_stability,
        global_total_calls=global_total_calls,
        global_failure_rate=global_failure_rate,
        global_avg_duration_ms=global_avg_duration_ms,
        busiest_tool=busiest_tool,
        most_failed_tool=most_failed_tool,
    )


def _durations(data: dict[str, object]) -> list[float]:
    values = data.get("durations")
    return values if isinstance(values, list) else []


def _failure_reasons(data: dict[str, object]) -> Counter[str]:
    values = data.get("failure_reasons")
    return values if isinstance(values, Counter) else Counter()


async def _collect_events(result: object) -> list[StructuredEvent]:
    from collections.abc import Awaitable
    if isinstance(result, list):
        return result
    if isinstance(result, AsyncIterable):
        return [event async for event in result]
    return list(await cast(Awaitable[Any], result))


__all__ = [
    "get_activity_patterns",
    "get_bash_audit_logs",
    "get_bash_execution_stats",
    "get_global_tool_stability",
    "get_session_summary",
    "get_tool_usage_stats",
]
