"""Tests for analytics_queries module — bash audit, tool usage, activity, stability."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.agent.event_log.analytics_queries import (
    get_activity_patterns,
    get_bash_audit_logs,
    get_bash_execution_stats,
    get_global_tool_stability,
    get_session_summary,
    get_tool_usage_stats,
)
from myrm_agent_harness.agent.event_log.types import EventFilter, EventPayload, StructuredEvent


class InMemoryBackend:
    def __init__(self, events: dict[str, list[StructuredEvent]] | None = None) -> None:
        self._events: dict[str, list[StructuredEvent]] = events or {}

    async def append(self, events: list[StructuredEvent]) -> None:
        for e in events:
            self._events.setdefault(e.session_id, []).append(e)

    async def get_events(self, session_id: str, event_filter: EventFilter | None = None) -> list[StructuredEvent]:
        events = self._events.get(session_id, [])
        if event_filter:
            if event_filter.start_time is not None:
                events = [e for e in events if e.timestamp >= event_filter.start_time]
            if event_filter.end_time is not None:
                events = [e for e in events if e.timestamp <= event_filter.end_time]
            if event_filter.event_types:
                events = [e for e in events if e.event_type in event_filter.event_types]
            if event_filter.limit:
                events = events[: event_filter.limit]
        return events

    async def get_all_session_ids(self) -> list[str]:
        return sorted(self._events.keys())


def _ev(seq: int, etype: str, sid: str = "s1", ts: float = 1700000000.0, **data: object) -> StructuredEvent:
    return StructuredEvent(
        sequence=seq, timestamp=ts + seq, event_type=etype, session_id=sid, data=EventPayload(**data)
    )


# ---- get_tool_usage_stats ----

@pytest.mark.asyncio
async def test_tool_usage_stats_basic() -> None:
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "tool_start", tool_name="Read"),
            _ev(2, "tool_end", tool_name="Read", duration_ms=100),
            _ev(3, "tool_start", tool_name="Read"),
            _ev(4, "tool_end", tool_name="Read", duration_ms=200),
            _ev(5, "tool_start", tool_name="Shell"),
            _ev(6, "tool_failure", tool_name="Shell", duration_ms=50, error_code="E001"),
        ],
    })
    stats = await get_tool_usage_stats(backend, "s1")
    assert len(stats) == 2
    read_stat = next(s for s in stats if s.tool_name == "Read")
    assert read_stat.total_calls == 2
    assert read_stat.success_count == 2
    assert read_stat.avg_duration_ms == 150.0
    shell_stat = next(s for s in stats if s.tool_name == "Shell")
    assert shell_stat.total_calls == 1
    assert shell_stat.failure_count == 1
    assert "E001" in shell_stat.failure_reasons


@pytest.mark.asyncio
async def test_tool_usage_stats_timeout_retry_tokens() -> None:
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "tool_start", tool_name="LLM"),
            _ev(2, "tool_timeout", tool_name="LLM"),
            _ev(3, "tool_retry", tool_name="LLM"),
            _ev(4, "tool_token_usage", tool_name="LLM", tokens=500),
            _ev(5, "tool_cancelled", tool_name="LLM", duration_ms=300),
        ],
    })
    stats = await get_tool_usage_stats(backend, "s1")
    assert len(stats) == 1
    s = stats[0]
    assert s.timeout_count == 1
    assert s.retry_count == 1
    assert s.total_tokens == 500


@pytest.mark.asyncio
async def test_tool_usage_stats_empty() -> None:
    backend = InMemoryBackend({"s1": []})
    stats = await get_tool_usage_stats(backend, "s1")
    assert stats == []


# ---- get_activity_patterns ----

@pytest.mark.asyncio
async def test_activity_patterns_basic() -> None:
    now = time.time()
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "tool_start", ts=now, tool_name="Read"),
            _ev(2, "tool_end", ts=now, tool_name="Read"),
        ],
    })
    patterns = await get_activity_patterns(backend, "s1")
    assert patterns.peak_tool == "Read"
    assert len(patterns.hourly_breakdown) >= 1


@pytest.mark.asyncio
async def test_activity_patterns_empty() -> None:
    backend = InMemoryBackend({"s1": []})
    patterns = await get_activity_patterns(backend, "s1")
    assert patterns.peak_hour == 0
    assert patterns.peak_tool == ""


# ---- get_bash_audit_logs ----

@pytest.mark.asyncio
async def test_bash_audit_logs_filters() -> None:
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "bash_command_executed", command_type="read", risk_level="low"),
            _ev(2, "bash_command_executed", command_type="write", risk_level="high"),
            _ev(3, "bash_command_executed", command_type="read", risk_level="high"),
        ],
    })
    all_logs = await get_bash_audit_logs(backend, "s1")
    assert len(all_logs) == 3

    filtered = await get_bash_audit_logs(backend, "s1", command_type="read")
    assert len(filtered) == 2

    filtered2 = await get_bash_audit_logs(backend, "s1", risk_level="high")
    assert len(filtered2) == 2

    filtered3 = await get_bash_audit_logs(backend, "s1", command_type="write", risk_level="high")
    assert len(filtered3) == 1


# ---- get_bash_execution_stats ----

@pytest.mark.asyncio
async def test_bash_execution_stats() -> None:
    now = time.time()
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "bash_command_executed", ts=now, success=True, duration_ms=100, command="ls", command_type="read"),
            _ev(2, "bash_command_executed", ts=now, success=True, duration_ms=200, command="cat", command_type="read"),
            _ev(3, "bash_command_executed", ts=now, success=False, duration_ms=50, command="rm", command_type="write", error_message="permission denied"),
        ],
    })
    stats = await get_bash_execution_stats(backend, "s1")
    assert stats.total_commands == 3
    assert abs(stats.success_rate - 2 / 3) < 0.01
    assert abs(stats.avg_duration_ms - (100 + 200 + 50) / 3) < 0.01
    assert len(stats.error_top10) >= 1
    assert len(stats.command_hotmap) >= 1
    assert "read" in stats.type_distribution


@pytest.mark.asyncio
async def test_bash_execution_stats_empty() -> None:
    backend = InMemoryBackend({"s1": []})
    stats = await get_bash_execution_stats(backend, "s1")
    assert stats.total_commands == 0
    assert stats.success_rate == 0.0


# ---- get_session_summary ----

@pytest.mark.asyncio
async def test_session_summary() -> None:
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "session_start"),
            _ev(2, "tool_start", tool_name="Read"),
            _ev(3, "tool_end", tool_name="Read", duration_ms=100),
            _ev(4, "session_end", summary={"duration_ms": 5000, "task_metrics": {"compression_count": 2}, "token_economics": {"usage": {"prompt_tokens": 100}}}),
        ],
    })
    summary = await get_session_summary(backend, "s1")
    assert summary.session_id == "s1"
    assert summary.duration_ms == 5000.0
    assert len(summary.tool_breakdown) == 1
    assert summary.tool_breakdown[0].tool_name == "Read"
    assert summary.tool_breakdown[0].call_count == 1
    assert summary.task_metrics["compression_count"] == 2
    assert summary.token_economics is not None


@pytest.mark.asyncio
async def test_session_summary_compactions_fallback() -> None:
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "session_end", summary={"duration_ms": 1000, "compactions": 3}),
        ],
    })
    summary = await get_session_summary(backend, "s1")
    assert summary.task_metrics["compression_count"] == 3


# ---- get_global_tool_stability ----

@pytest.mark.asyncio
async def test_global_tool_stability() -> None:
    now = time.time()
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "tool_start", ts=now, tool_name="Read"),
            _ev(2, "tool_end", ts=now, tool_name="Read", duration_ms=100),
            _ev(3, "tool_start", ts=now, tool_name="Read"),
            _ev(4, "tool_failure", ts=now, tool_name="Read", duration_ms=200, error_code="IO_ERR"),
        ],
        "s2": [
            _ev(1, "tool_start", ts=now, tool_name="Read"),
            _ev(2, "tool_timeout", ts=now, tool_name="Read"),
        ],
    })
    result = await get_global_tool_stability(backend, ["s1", "s2"])
    assert result.global_total_calls == 3
    assert result.global_failure_rate > 0
    assert result.busiest_tool == "Read"
    assert len(result.daily_stability) >= 1
    day = result.daily_stability[0]
    assert day.failure_count >= 1


@pytest.mark.asyncio
async def test_global_tool_stability_with_tool_filter() -> None:
    now = time.time()
    backend = InMemoryBackend({
        "s1": [
            _ev(1, "tool_start", ts=now, tool_name="Read"),
            _ev(2, "tool_end", ts=now, tool_name="Read", duration_ms=50),
            _ev(3, "tool_start", ts=now, tool_name="Shell"),
            _ev(4, "tool_end", ts=now, tool_name="Shell", duration_ms=300),
        ],
    })
    result = await get_global_tool_stability(backend, ["s1"], tool_name="Read")
    assert result.global_total_calls == 1


@pytest.mark.asyncio
async def test_global_tool_stability_empty() -> None:
    backend = InMemoryBackend({"s1": []})
    result = await get_global_tool_stability(backend, ["s1"])
    assert result.global_total_calls == 0
    assert result.global_failure_rate == 0.0
    assert result.busiest_tool is None
