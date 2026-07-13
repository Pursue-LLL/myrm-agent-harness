"""EventLogger — integration façade for the event log subsystem.

Receives raw agent events, classifies them (persist or skip),
sanitizes PII/secrets, buffers writes, and manages session lifecycle
events (SESSION_START / SESSION_END with summary).

Every event is automatically enriched with context dimensions
(user_id, agent_id, task_type, trace_id) for downstream analytics,
task-level replay, and OpenTelemetry correlation.

[INPUT]
- event_log.protocol::EventLogBackend (POS: Protocol contract. Framework provides FileEventLogBackend; business layer may extend with SQLite / PostgreSQL implementations.)
- infra.tracing.propagation::get_current_trace_id (POS: Trace上下文传播)
- security.detection::leak_detector, (POS: Unicode  ID)

[OUTPUT]
- EventLogger: main entry point for event recording

[POS]
Integration façade. Injected into BaseAgent via ``event_log_backend`` param.
Async-buffered writes ensure zero impact on the event production hot path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .types import (
    ActivityPatterns,
    EventPayload,
    SessionAnalytics,
    SessionSummary,
    StructuredEvent,
    ToolUsageStats,
    get_persistent_event_types,
)

if TYPE_CHECKING:
    from .protocols import EventLogBackend

logger = logging.getLogger(__name__)

_FLUSH_BATCH_SIZE = 50
_FLUSH_INTERVAL_S = 0.5
_CLOSE_TIMEOUT_S = 5.0
_MAX_FIELD_BYTES = 4096

_SESSION_START = "session_start"
_SESSION_END = "session_end"
_SECURITY_AUDIT = "security_audit"

_COUNTER_TYPES: dict[str, str] = {
    "tool_start": "tool_call_count",
    "error": "error_count",
    "tool_approval_request": "approval_count",
}


class EventLogger:
    """Async-buffered event logger with session lifecycle management.

    Context dimensions (user_id, agent_id, task_type) are injected into
    every event's ``data`` dict with ``_`` prefix to separate framework
    metadata from business payload.  The active OpenTelemetry trace_id
    is captured per-event for cross-system correlation.
    """

    def __init__(
        self,
        backend: EventLogBackend,
        session_id: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
    ) -> None:
        self._backend = backend
        self._session_id = session_id
        self._user_id = user_id
        self._agent_id = agent_id
        self._task_type = task_type
        self._sequence = 0
        self._summary = SessionSummary()
        self._buffer: list[StructuredEvent] = []
        self._writer_task: asyncio.Task[None] | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._queue: asyncio.Queue[StructuredEvent | None] = asyncio.Queue()
        self._closed = False

    async def start(self) -> None:
        """Emit SESSION_START and launch the background writer."""
        self._summary.start_time = time.time()
        self._writer_task = asyncio.create_task(self._writer_loop())
        await self._enqueue(self._make_event(_SESSION_START, {}))

        # Cleanup old logs (fire-and-forget, non-blocking)
        cleanup_task = asyncio.create_task(self._cleanup_old_logs_async())
        self._bg_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._bg_tasks.discard)

    async def log(self, event_type: str, data: dict[str, object]) -> None:
        """Record an event if its type is in the persistent set.

        Non-blocking: puts the event into an async queue for the
        background writer to consume.
        """
        if self._closed:
            return

        persistent = get_persistent_event_types()
        if event_type not in persistent:
            return

        self._update_counters(event_type, data)

        sanitized = self._sanitize(data)
        capped = _cap_data_size(sanitized)
        event = self._make_event(event_type, capped)
        await self._enqueue(event)

    async def flush_security_audit(self) -> None:
        """Batch-write all SecurityDecision entries from the current session."""
        try:
            from myrm_agent_harness.agent.security.audit import get_audit_entries

            entries = get_audit_entries()
            if not entries:
                return

            self._summary.security_decision_count = len(entries)
            audit_data: dict[str, object] = {
                "decisions": [e.to_dict() for e in entries],
                "count": len(entries),
            }
            await self._enqueue(self._make_event(_SECURITY_AUDIT, audit_data))
        except Exception:
            logger.debug("Failed to flush security audit", exc_info=True)

    async def close(self) -> None:
        """Emit SESSION_END + summary, flush buffer, stop writer."""
        if self._closed:
            return
        self._closed = True

        await self.flush_security_audit()
        self._attach_runtime_metrics()

        elapsed_ms = int((time.time() - self._summary.start_time) * 1000)
        self._summary.duration_ms = elapsed_ms
        self._summary.total_events += 1  # count session_end itself
        end_data: dict[str, object] = {"summary": self._summary.to_dict()}
        self._sequence += 1
        end_event = StructuredEvent(
            sequence=self._sequence,
            timestamp=time.time(),
            event_type=_SESSION_END,
            session_id=self._session_id,
            data=EventPayload(**end_data),
        )
        await self._enqueue(end_event)

        # Print CLI Summary for developers
        try:
            from myrm_agent_harness.agent.event_log.cli_summary import generate_cli_summary

            cli_summary = generate_cli_summary(self._session_id, self._summary.to_dict())
            print(cli_summary)
        except Exception as e:
            logger.debug(f"Failed to generate CLI summary: {e}")

        self._queue.put_nowait(None)

        if self._writer_task:
            try:
                await asyncio.wait_for(self._writer_task, timeout=_CLOSE_TIMEOUT_S)
            except TimeoutError:
                logger.warning(
                    f"EventLogger close timed out after {_CLOSE_TIMEOUT_S}s, {self._queue.qsize()} events may be lost"
                )
                self._writer_task.cancel()

        if self._buffer:
            try:
                await self._backend.append(self._buffer)
            except Exception:
                logger.warning("Failed final flush", exc_info=True)
            self._buffer.clear()

        try:
            await self._backend.close()
        except Exception:
            logger.debug("Backend close error", exc_info=True)

    def _make_event(self, event_type: str, data: dict[str, object]) -> StructuredEvent:
        self._sequence += 1
        self._summary.total_events += 1

        enriched = self._enrich_data(data)

        return StructuredEvent(
            sequence=self._sequence,
            timestamp=time.time(),
            event_type=event_type,
            session_id=self._session_id,
            data=EventPayload(**enriched),
        )

    def _enrich_data(self, data: dict[str, object]) -> dict[str, object]:
        """Inject context dimensions into event data for analytics and correlation."""
        enriched = dict(data)
        if self._user_id:
            enriched["_user_id"] = self._user_id
        if self._agent_id:
            enriched["_agent_id"] = self._agent_id
        if self._task_type:
            enriched["_task_type"] = self._task_type
        try:
            from myrm_agent_harness.infra.tracing.propagation import get_current_trace_id

            trace_id = get_current_trace_id()
            if trace_id:
                enriched["_trace_id"] = trace_id
        except ImportError:
            pass
        return enriched

    async def _enqueue(self, event: StructuredEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("Event queue full, dropping event seq=%d", event.sequence)

    async def _cleanup_old_logs_async(self) -> None:
        """Cleanup old event logs (fire-and-forget background task)."""
        try:
            # Check if backend supports cleanup (FileEventLogBackend does)
            if hasattr(self._backend, "cleanup_old_logs"):
                deleted_count = await self._backend.cleanup_old_logs()
                if deleted_count > 0:
                    logger.info(f"Event log cleanup: removed {deleted_count} old log files")
        except Exception as e:
            logger.warning(f"Event log cleanup failed: {e}")

    def _update_counters(self, event_type: str, data: dict[str, object]) -> None:
        attr = _COUNTER_TYPES.get(event_type)
        if attr:
            setattr(self._summary, attr, getattr(self._summary, attr) + 1)

        if event_type == "status":
            kind = data.get("kind")
            if kind == "compaction":
                self._summary.compaction_count += 1
            elif kind == "model_failover":
                self._summary.failover_count += 1

    def set_action_space_metrics(self, runtime_skills: int, runtime_tools: int) -> None:
        """Record the runtime action space size for SESSION SUMMARY observability."""
        self._summary.runtime_skills = runtime_skills
        self._summary.runtime_tools = runtime_tools

    def _attach_runtime_metrics(self) -> None:
        """Attach request-scoped token and compaction metrics before SESSION_END."""
        try:
            from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

            tracker = get_token_tracker()
            if tracker is not None:
                self._summary.token_economics = tracker.to_dict()
        except Exception:
            logger.debug("Failed to attach token tracker metrics", exc_info=True)

        try:
            from myrm_agent_harness.agent.context_management.tracking.task_metrics import get_task_metrics

            metrics = get_task_metrics(self._session_id)
            if metrics is not None and metrics.compression_count > 0:
                self._summary.task_metrics = metrics.to_dict()
                if self._summary.compaction_count < metrics.compression_count:
                    self._summary.compaction_count = metrics.compression_count
        except Exception:
            logger.debug("Failed to attach context task metrics", exc_info=True)

    @staticmethod
    def _sanitize(data: dict[str, object]) -> dict[str, object]:
        """Remove secrets and PII from event data before persistence."""
        try:
            from myrm_agent_harness.agent.security.detection.leak_detector import (
                redact_leaks,
            )

            text_fields = {k: v for k, v in data.items() if isinstance(v, str)}
            if text_fields:
                sanitized = dict(data)
                for key, val in text_fields.items():
                    sanitized[key] = redact_leaks(val)
                return sanitized
        except (ImportError, TypeError):
            pass
        except Exception:
            logger.debug("Sanitization error, persisting as-is", exc_info=True)

        return data

    async def _writer_loop(self) -> None:
        """Background task: drain queue → batch append to backend."""
        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=_FLUSH_INTERVAL_S)
            except TimeoutError:
                if self._buffer:
                    await self._flush()
                continue

            if event is None:
                break

            self._buffer.append(event)
            if len(self._buffer) >= _FLUSH_BATCH_SIZE:
                await self._flush()

        if self._buffer:
            await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return
        batch = list(self._buffer)
        self._buffer.clear()
        try:
            await self._backend.append(batch)
        except Exception:
            self._summary.dropped_event_count += len(batch)
            logger.warning(f"Failed to flush {len(batch)} events", exc_info=True)

    # --- Tool Usage Analytics (A1) ---

    async def get_tool_usage_stats(self, time_range_seconds: float | None = None) -> list[ToolUsageStats]:
        """Query tool usage statistics for the current session.

        Args:
            time_range_seconds: Optional time range in seconds from **current time** (not session start).
                              For example, 3600 means "last 1 hour from now", 86400 means "last 24 hours".
                              If None, includes all events in the session.

        Returns:
            List of ToolUsageStats sorted by total_calls (descending)
        """
        from .analytics_queries import get_tool_usage_stats as _get_tool_usage_stats

        return await _get_tool_usage_stats(
            self._backend,
            self._session_id,
            time_range_seconds=time_range_seconds,
        )

    async def get_activity_patterns(self, time_range_seconds: float | None = None) -> ActivityPatterns:
        """Query activity patterns (hourly breakdown) for the current session.

        Args:
            time_range_seconds: Optional time range in seconds from **current time** (not session start).
                              For example, 3600 means "last 1 hour from now".
                              If None, includes all events in the session.

        Returns:
            ActivityPatterns with hourly breakdown, peak hour, and peak tool
        """
        from .analytics_queries import get_activity_patterns as _get_activity_patterns

        return await _get_activity_patterns(
            self._backend,
            self._session_id,
            time_range_seconds=time_range_seconds,
        )

    # --- Bash Command Auditing (A4) ---

    async def get_bash_audit_logs(
        self,
        start_time: float | None = None,
        end_time: float | None = None,
        command_type: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[StructuredEvent]:
        """Query bash command audit logs for the current session.

        Args:
            start_time: Optional start time (UTC timestamp)
            end_time: Optional end time (UTC timestamp)
            command_type: Optional command type filter (READ/WRITE/DANGEROUS/etc.)
            risk_level: Optional risk level filter (LOW/MEDIUM/HIGH)
            limit: Maximum number of logs to return (default 100)

        Returns:
            List of StructuredEvent sorted by timestamp (descending)
        """
        from .analytics_queries import get_bash_audit_logs as _get_bash_audit_logs

        return await _get_bash_audit_logs(
            self._backend,
            self._session_id,
            start_time=start_time,
            end_time=end_time,
            command_type=command_type,
            risk_level=risk_level,
            limit=limit,
        )

    async def get_bash_execution_stats(self) -> dict[str, object]:
        """Get bash command execution statistics for the current session.

        Returns:
            Dict containing statistics:
            - total_commands: int
            - success_rate: float
            - avg_duration_ms: float
            - error_top10: list[(error_message, count)]
            - command_hotmap: list[(command, count)] Top10
            - type_distribution: dict[command_type, count]
            - hourly_breakdown: list[(hour, count)]
        """
        from .analytics_queries import get_bash_execution_stats as _get_bash_execution_stats

        stats = await _get_bash_execution_stats(self._backend, self._session_id)
        return {
            "total_commands": stats.total_commands,
            "success_rate": stats.success_rate,
            "avg_duration_ms": stats.avg_duration_ms,
            "error_top10": stats.error_top10,
            "command_hotmap": stats.command_hotmap,
            "type_distribution": stats.type_distribution,
            "hourly_breakdown": stats.hourly_breakdown,
        }

    async def get_session_summary(
        self,
        events_limit: int = 150,
        timeline_limit: int = 100,
    ) -> SessionAnalytics:
        """Get comprehensive session analytics summary.

        Aggregates EventLog data to provide a complete view of session performance,
        tool usage, and execution timeline. Intended for analytics dashboards and
        session detail views.

        Args:
            events_limit: Maximum number of events to expose in timeline loading (default: 150).
                Tool breakdown and session_end summary are aggregated from their complete event streams.
            timeline_limit: Maximum number of events to include in timeline (default: 100).

        Returns:
            SessionAnalytics with duration, tool_breakdown, events_timeline, task_metrics.
        """
        from .analytics_queries import get_session_summary as _get_session_summary

        return await _get_session_summary(
            self._backend,
            self._session_id,
            events_limit=events_limit,
            timeline_limit=timeline_limit,
        )


def _cap_data_size(data: dict[str, object]) -> dict[str, object]:
    """Truncate string values exceeding ``_MAX_FIELD_BYTES`` to prevent oversized events."""
    needs_cap = False
    for v in data.values():
        if isinstance(v, str) and len(v) > _MAX_FIELD_BYTES:
            needs_cap = True
            break

    if not needs_cap:
        return data

    capped = dict(data)
    for k, v in capped.items():
        if isinstance(v, str) and len(v) > _MAX_FIELD_BYTES:
            capped[k] = v[:_MAX_FIELD_BYTES] + " [truncated]"
    return capped
