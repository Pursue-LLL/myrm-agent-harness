"""Event Log — append-only event journal for audit, replay, and observability.

Framework-layer module providing structured event persistence alongside
LangGraph Checkpointer. The checkpointer handles state snapshots for fast
recovery; the event log captures the full decision trail for audit,
debugging, cross-session analysis, and task-level replay.

[INPUT]
- agent.types::AgentEventType (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- security.audit::SecurityDecision (POS: Cross-cutting concern. Called from tool_interceptor_middleware and all security guard modules at every decision point.)
- security.detection::leak_detector, (POS: Unicode  ID)
- infra.tracing.propagation::get_current_trace_id (POS: Trace)

[OUTPUT]
- EventLogBackend: 5th framework protocol (append / query / get_all_session_ids / close)
- StructuredEvent: typed event record
- EventLogger: session-level analysis (classify → sanitize → buffer → write + analytics)
- EventLogAnalytics: global-level analysis (cross-session aggregation)
- FileEventLogBackend: built-in JSONL file backend
- ExecutionTrace: task-level aggregation for replay and scoring
- TraceMetadata: context dimensions (user_id, agent_id, task_type, trace_id)
- Data classes: ToolUsageStats, ActivityPatterns, DailyActivity, GlobalActivityPatterns

[POS]
Complements Checkpointer with full event history. Optional — omitting
``event_log_backend`` leaves agent behaviour unchanged.
"""

from .analytics import EventLogAnalytics
from .logger import EventLogger
from .protocols import EventLogBackend
from .trace_types import ExecutionTrace, ToolCallRecord, TraceMetadata, TraceOutcome
from .types import (
    ActivityPatterns,
    BashExecutionStats,
    DailyActivity,
    EventFilter,
    GlobalActivityPatterns,
    HourlyToolUsage,
    SessionAnalytics,
    SessionEvent,
    SessionSummary,
    StructuredEvent,
    ToolBreakdown,
    ToolStabilityAnalytics,
    ToolStabilityDaily,
    ToolUsageStats,
)

__all__ = [
    "ActivityPatterns",
    "BashExecutionStats",
    "DailyActivity",
    "EventFilter",
    "EventLogAnalytics",
    "EventLogBackend",
    "EventLogger",
    "ExecutionTrace",
    "GlobalActivityPatterns",
    "HourlyToolUsage",
    "SessionAnalytics",
    "SessionEvent",
    "SessionSummary",
    "StructuredEvent",
    "ToolBreakdown",
    "ToolCallRecord",
    "ToolStabilityAnalytics",
    "ToolStabilityDaily",
    "ToolUsageStats",
    "TraceMetadata",
    "TraceOutcome",
]
