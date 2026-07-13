"""Event log type definitions — zero-dependency pure types.

[INPUT]
- agent.types::AgentEventType (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- StructuredEvent: immutable event record
- EventFilter: query parameter object
- SessionSummary: deterministic session statistics
- PERSISTENT_EVENT_TYPES: set of event types that get written to the log

[POS]
Single source of truth for event log data structures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from myrm_agent_harness.agent.streaming.types import AgentEventType


class EventPayload(BaseModel):
    """Base class for strongly typed event payloads.
    Allows extra fields for backward compatibility and dynamic enrichment.
    """

    model_config = ConfigDict(extra="allow")

    def get(self, key: str, default: Any = None) -> Any:
        """Backward compatibility for dict.get()"""
        if hasattr(self, key):
            return getattr(self, key)
        return self.model_extra.get(key, default) if self.model_extra else default

    def __getitem__(self, item: str) -> Any:
        """Backward compatibility for dict subscripting"""
        if hasattr(self, item):
            return getattr(self, item)
        if self.model_extra and item in self.model_extra:
            return self.model_extra[item]
        raise KeyError(item)

    def items(self) -> Any:
        """Backward compatibility for dict.items()"""
        return self.model_dump().items()


class StructuredEvent(BaseModel):
    """Immutable event record for the append-only log.

    IMPORTANT: All timestamps must be Unix epoch time in UTC (seconds since 1970-01-01 00:00:00 UTC).
    This ensures consistent time-based queries across timezones.
    """

    model_config = ConfigDict(frozen=True)

    sequence: int
    timestamp: float  # UTC Unix timestamp (seconds since epoch)
    event_type: str
    session_id: str
    data: EventPayload

    def to_dict(self) -> dict[str, object]:
        return {
            "seq": self.sequence,
            "ts": round(self.timestamp, 3),
            "type": self.event_type,
            "sid": self.session_id,
            "data": self.data.model_dump(),
        }


@dataclass(frozen=True, slots=True)
class EventFilter:
    """Query parameter object for ``EventLogBackend.get_events()``.

    Time filters use UTC Unix timestamps for consistency.
    """

    event_types: frozenset[str] | None = None
    start_time: float | None = None  # UTC Unix timestamp
    end_time: float | None = None  # UTC Unix timestamp
    start_sequence: int | None = None
    limit: int | None = None


@dataclass(slots=True)
class SessionSummary:
    """Deterministic session statistics — zero LLM, pure counters.

    Extended with token and message statistics for comprehensive session analytics.
    """

    total_events: int = 0
    tool_call_count: int = 0
    error_count: int = 0
    approval_count: int = 0
    compaction_count: int = 0
    failover_count: int = 0
    security_decision_count: int = 0
    dropped_event_count: int = 0
    duration_ms: int = 0
    start_time: float = field(default_factory=time.time)

    # Token statistics (for Top Sessions analytics)
    message_count: int = 0
    task_metrics: dict[str, object] = field(default_factory=dict)
    token_economics: dict[str, object] | None = None

    # Action space metrics (for observability of Opt-In effectiveness)
    runtime_skills: int | None = None
    runtime_tools: int | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "total_events": self.total_events,
            "tool_calls": self.tool_call_count,
            "errors": self.error_count,
            "approvals": self.approval_count,
            "compactions": self.compaction_count,
            "failovers": self.failover_count,
            "security_decisions": self.security_decision_count,
            "duration_ms": self.duration_ms,
            "message_count": self.message_count,
        }
        if self.task_metrics:
            result["task_metrics"] = self.task_metrics
        if self.dropped_event_count > 0:
            result["dropped_events"] = self.dropped_event_count
        if self.token_economics:
            result["token_economics"] = self.token_economics
        if self.runtime_skills is not None:
            result["runtime_skills"] = self.runtime_skills
        if self.runtime_tools is not None:
            result["runtime_tools"] = self.runtime_tools
        return result


def _build_persistent_types() -> frozenset[str]:
    """Build the set of event types that should be persisted.

    Excludes high-frequency streaming chunks (MESSAGE, REASONING)
    and ephemeral UI events (UI_UPDATE, ARTIFACT_CONTENT) to
    keep ~60-70% of event volume out of the log.
    """

    exclude: set[str] = {
        AgentEventType.MESSAGE.value,
        AgentEventType.REASONING.value,
        AgentEventType.UI_UPDATE.value,
        AgentEventType.ARTIFACT_CONTENT.value,
    }
    return frozenset(e.value for e in AgentEventType if e.value not in exclude) | frozenset(
        {"user_interruption", "trace_run_digest", "llm_request", "takeover_trace"}
    )


PERSISTENT_EVENT_TYPES: frozenset[str] | None = None


def get_persistent_event_types() -> frozenset[str]:
    """Lazy-initialise and return persistent event types."""
    global PERSISTENT_EVENT_TYPES
    if PERSISTENT_EVENT_TYPES is None:
        PERSISTENT_EVENT_TYPES = _build_persistent_types()
    return PERSISTENT_EVENT_TYPES


# --- Tool Usage Analytics (A1) ---


@dataclass(frozen=True, slots=True)
class ToolUsageStats:
    """Tool usage statistics for analytics."""

    tool_name: str
    total_calls: int
    success_count: int
    failure_count: int
    timeout_count: int
    retry_count: int
    avg_duration_ms: float
    failure_reasons: dict[str, int]  # error_code -> count
    total_tokens: int = 0
    avg_tokens: float = 0.0


@dataclass(frozen=True, slots=True)
class HourlyToolUsage:
    """Hourly tool usage breakdown."""

    hour: int  # 0-23
    tool_name: str
    call_count: int
    avg_duration_ms: float


@dataclass(frozen=True, slots=True)
class ActivityPatterns:
    """Activity pattern analysis."""

    hourly_breakdown: list[HourlyToolUsage]
    peak_hour: int
    peak_tool: str


# --- Global Activity Analytics (A2) ---


@dataclass(frozen=True, slots=True)
class DailyActivity:
    """Daily activity statistics."""

    date: str  # "YYYY-MM-DD"
    day_of_week: int  # 0=Monday ... 6=Sunday
    session_count: int
    tool_calls: int
    duration_ms: float


@dataclass(frozen=True, slots=True)
class ToolStabilityDaily:
    """Daily aggregated tool stability statistics."""

    date: str  # "YYYY-MM-DD"
    tool_name: str
    total_calls: int
    success_count: int
    failure_count: int
    timeout_count: int
    avg_duration_ms: float
    p90_duration_ms: float
    p99_duration_ms: float
    failure_rate: float
    failure_reasons: dict[str, int]  # error_code/reason -> count


@dataclass(frozen=True, slots=True)
class ToolStabilityAnalytics:
    """Global (cross-session) tool stability analytics."""

    daily_stability: list[ToolStabilityDaily]
    global_total_calls: int
    global_failure_rate: float
    global_avg_duration_ms: float
    busiest_tool: str | None
    most_failed_tool: str | None


@dataclass(frozen=True, slots=True)
class GlobalActivityPatterns:
    """Global (cross-session) activity pattern analysis."""

    daily_activities: list[DailyActivity]
    by_day_of_week: dict[int, int]  # day_of_week -> total_tool_calls
    by_hour: dict[int, int]  # hour -> total_tool_calls
    active_days: int
    max_streak: int
    busiest_day_of_week: int
    busiest_hour: int


# --- Top Sessions Analytics (A3) ---


@dataclass(frozen=True, slots=True)
class TopSession:
    """Top session record for analytics.

    Represents a notable session identified by a specific metric
    (e.g., longest duration, most tokens, most tool calls).
    """

    session_id: str
    metric_value: float  # The value of the metric being ranked (duration, tokens, etc.)
    metric_type: str  # "duration", "messages", "tokens", "tool_calls"
    started_at: float  # UTC timestamp
    duration_ms: float
    message_count: int
    total_tokens: int  # input + output + cache_read + cache_write
    tool_calls: int


# --- Bash Command Auditing (A4) ---


@dataclass(frozen=True, slots=True)
class BashExecutionStats:
    """Bash command execution statistics."""

    total_commands: int
    success_rate: float
    avg_duration_ms: float
    error_top10: list[tuple[str, int]]  # (error_message, count)
    command_hotmap: list[tuple[str, int]]  # (command, count) Top10
    type_distribution: dict[str, int]  # command_type -> count
    hourly_breakdown: list[tuple[int, int]]  # (hour, count)


# --- Session Summary (B2) ---


@dataclass(frozen=True, slots=True)
class ToolBreakdown:
    """Tool usage breakdown for a single tool."""

    tool_name: str
    call_count: int
    total_duration_ms: float


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """Single event in session timeline."""

    event_type: str
    timestamp: float
    data: EventPayload


@dataclass(frozen=True, slots=True)
class SessionAnalytics:
    """Comprehensive session analytics summary.

    Aggregates EventLog data to provide a complete view of session performance,
    tool usage, and execution timeline. Intended for analytics dashboards and
    session detail views.
    """

    session_id: str
    duration_ms: float
    tool_breakdown: list[ToolBreakdown]
    events_timeline: list[SessionEvent]
    task_metrics: dict[str, object]  # Extensible for future task metrics
    token_economics: dict[str, object] | None = None


# --- Trace Evidence (skill evolution input) ---


@dataclass(frozen=True, slots=True)
class FileHotspot:
    """A file that is frequently accessed or modified during a specific feature/task."""

    file_path: str
    read_count: int
    write_count: int
    last_accessed: float

    def to_dict(self) -> dict[str, object]:
        return {
            "file_path": self.file_path,
            "read_count": self.read_count,
            "write_count": self.write_count,
            "last_accessed": self.last_accessed,
        }


@dataclass(frozen=True, slots=True)
class AntiPattern:
    """An anti-pattern extracted from tool failures or user interruptions."""

    error_signature: str
    failed_tool: str
    failed_args: dict[str, object]
    user_correction: str | None  # If the user took over and fixed it, what did they do?
    timestamp: float

    def to_dict(self) -> dict[str, object]:
        return {
            "error_signature": self.error_signature,
            "failed_tool": self.failed_tool,
            "failed_args": self.failed_args,
            "user_correction": self.user_correction,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class TraceRunDigest:
    """Extracted evidence from a trace for skill evolution and analytics."""

    session_id: str
    task_intent: str | None
    hotspots: list[FileHotspot]
    anti_patterns: list[AntiPattern]
    success_rate: float
    duration_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "task_intent": self.task_intent,
            "hotspots": [h.to_dict() for h in self.hotspots],
            "anti_patterns": [a.to_dict() for a in self.anti_patterns],
            "success_rate": self.success_rate,
            "duration_ms": self.duration_ms,
        }
