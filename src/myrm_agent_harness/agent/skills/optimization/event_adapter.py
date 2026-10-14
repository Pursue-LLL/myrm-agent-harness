"""EventLog Adapter for Skill Execution Provider

[INPUT]
- .protocols.SkillExecutionProvider (POS: execution event provider interface)
- agent.event_log.protocol.EventLogBackend (POS: EventLog backend interface)

[OUTPUT]
- EventLogAdapter: EventLog-backed SkillExecutionProvider

[POS]
Framework adapter: rebuild SkillExecutionSample rows from persisted tool_start / tool_end / tool_failure events.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from myrm_agent_harness.core.events.types import AgentEventType

from .protocols import SkillExecutionProvider, SkillExecutionSample

if TYPE_CHECKING:
    from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
    from myrm_agent_harness.agent.event_log.types import StructuredEvent

logger = logging.getLogger(__name__)

_TOOL_LIFECYCLE_TYPES = frozenset(
    {
        AgentEventType.TOOL_START.value,
        AgentEventType.TOOL_END.value,
        AgentEventType.TOOL_FAILURE.value,
    }
)


def _event_data(event: StructuredEvent) -> dict[str, object]:
    return event.data.model_dump()


def _tool_names_for_skill(skill_id: str, tool_name_aliases: frozenset[str] | None) -> frozenset[str]:
    names = {skill_id, f"skill_{skill_id}"}
    if tool_name_aliases:
        names |= set(tool_name_aliases)
    return frozenset(names)


class EventLogAdapter(SkillExecutionProvider):
    """Read skill execution samples from the append-only EventLog."""

    def __init__(self, event_log_backend: EventLogBackend) -> None:
        self.event_log_backend = event_log_backend

    async def get_skill_executions(
        self,
        skill_id: str,
        days: int = 7,
        session_id: str | None = None,
        *,
        tool_name_aliases: frozenset[str] | None = None,
    ) -> list[SkillExecutionSample]:
        samples: list[SkillExecutionSample] = []
        allowed_tools = _tool_names_for_skill(skill_id, tool_name_aliases)
        cutoff_time = datetime.now(tz=UTC) - timedelta(days=days)
        cutoff_ts = cutoff_time.timestamp()

        try:
            session_ids = [session_id] if session_id else await self.event_log_backend.get_all_session_ids()

            for sid in session_ids:
                events = await self.event_log_backend.get_events(sid)
                tool_events = self._filter_tool_events(events, allowed_tools, cutoff_ts)
                samples.extend(self._pair_tool_events(tool_events, skill_id))

            return samples

        except Exception as e:
            logger.error("Failed to query EventLog for skill %s: %s", skill_id, e)
            return []

    async def collect_tool_names(self, *, days: int = 30) -> set[str]:
        """Distinct tool_name values from tool_start events in the retention window."""
        cutoff_ts = (datetime.now(tz=UTC) - timedelta(days=days)).timestamp()
        names: set[str] = set()
        try:
            for sid in await self.event_log_backend.get_all_session_ids():
                for event in await self.event_log_backend.get_events(sid):
                    if event.event_type != AgentEventType.TOOL_START.value:
                        continue
                    if event.timestamp < cutoff_ts:
                        continue
                    tool_name = _event_data(event).get("tool_name")
                    if isinstance(tool_name, str) and tool_name:
                        names.add(tool_name)
        except Exception as e:
            logger.error("Failed to collect tool names from EventLog: %s", e)
        return names

    async def get_all_skill_ids(self) -> list[str]:
        """Legacy helper: returns tool names (not catalog ids) seen in the log."""
        return sorted(await self.collect_tool_names())

    async def count_executions(self, skill_id: str, days: int = 7) -> int:
        samples = await self.get_skill_executions(skill_id, days)
        return len(samples)

    def _filter_tool_events(
        self,
        events: list[StructuredEvent],
        allowed_tools: frozenset[str],
        cutoff_ts: float,
    ) -> list[StructuredEvent]:
        filtered: list[StructuredEvent] = []
        for event in events:
            if event.event_type not in _TOOL_LIFECYCLE_TYPES:
                continue
            if event.timestamp < cutoff_ts:
                continue
            tool_name = _event_data(event).get("tool_name")
            if not isinstance(tool_name, str) or tool_name not in allowed_tools:
                continue
            filtered.append(event)
        return filtered

    def _pair_tool_events(self, events: list[StructuredEvent], skill_id: str) -> list[SkillExecutionSample]:
        event_groups: dict[str, dict[str, StructuredEvent]] = {}

        for event in events:
            data = _event_data(event)
            tool_call_id = data.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                continue
            event_groups.setdefault(tool_call_id, {})[event.event_type] = event

        samples: list[SkillExecutionSample] = []

        for group in event_groups.values():
            start_event = group.get(AgentEventType.TOOL_START.value)
            if start_event is None:
                continue

            end_event = group.get(AgentEventType.TOOL_END.value)
            failure_event = group.get(AgentEventType.TOOL_FAILURE.value)
            if end_event is None and failure_event is None:
                continue

            terminal = end_event if end_event is not None else failure_event
            assert terminal is not None

            success = end_event is not None
            duration_seconds = self._duration_seconds(start_event, terminal)
            tokens_used = self._token_count(terminal)
            executed_at = datetime.fromtimestamp(start_event.timestamp, tz=UTC)
            model_id = self._model_id(start_event)

            samples.append(
                SkillExecutionSample(
                    skill_id=skill_id,
                    success=success,
                    tokens_used=tokens_used,
                    execution_time=duration_seconds,
                    user_feedback=None,
                    timestamp=executed_at,
                    model_id=model_id,
                )
            )

        return samples

    def _duration_seconds(self, start_event: StructuredEvent, end_event: StructuredEvent) -> float:
        data = _event_data(end_event)
        duration_ms = data.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
            return float(duration_ms) / 1000.0

        start_data = _event_data(start_event)
        start_time = start_data.get("start_time")
        end_time = data.get("end_time")
        if isinstance(start_time, (int, float)) and isinstance(end_time, (int, float)):
            return max(float(end_time) - float(start_time), 0.0)

        return max(end_event.timestamp - start_event.timestamp, 0.0)

    def _token_count(self, end_event: StructuredEvent) -> int:
        token_count = _event_data(end_event).get("token_count")
        if isinstance(token_count, int) and token_count >= 0:
            return token_count
        return 0

    @staticmethod
    def _model_id(start_event: StructuredEvent) -> str | None:
        data = _event_data(start_event)
        for key in ("model_id", "llm_model", "model"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
