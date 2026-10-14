"""EventLogAdapter builds SkillExecutionSample rows from tool lifecycle events."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.types import EventPayload, StructuredEvent
from myrm_agent_harness.agent.skills.optimization.event_adapter import EventLogAdapter
from myrm_agent_harness.core.events.types import AgentEventType


@pytest.mark.asyncio
async def test_event_adapter_pairs_tool_start_and_tool_end(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    session_id = "chat-1"
    backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
    now = time.time()

    start = StructuredEvent(
        sequence=1,
        timestamp=now,
        event_type=AgentEventType.TOOL_START.value,
        session_id=session_id,
        data=EventPayload(
            tool_name="pdf-tools",
            tool_call_id="call-1",
            start_time=now,
            status="started",
        ),
    )
    end = StructuredEvent(
        sequence=2,
        timestamp=now + 1.5,
        event_type=AgentEventType.TOOL_END.value,
        session_id=session_id,
        data=EventPayload(
            tool_name="pdf-tools",
            tool_call_id="call-1",
            start_time=now,
            end_time=now + 1.5,
            duration_ms=1500,
            status="completed",
        ),
    )
    await backend.append([start, end])

    adapter = EventLogAdapter(backend)
    samples = await adapter.get_skill_executions("pdf-tools", days=7, tool_name_aliases=frozenset({"pdf-tools"}))

    assert len(samples) == 1
    sample = samples[0]
    assert sample.skill_id == "pdf-tools"
    assert sample.success is True
    assert sample.execution_time == pytest.approx(1.5, rel=0.01)
    assert sample.timestamp.timestamp() == pytest.approx(now, abs=0.001)


@pytest.mark.asyncio
async def test_event_adapter_records_tool_failure_as_unsuccessful(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    session_id = "chat-2"
    backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
    now = time.time()

    await backend.append(
        [
            StructuredEvent(
                sequence=1,
                timestamp=now,
                event_type=AgentEventType.TOOL_START.value,
                session_id=session_id,
                data=EventPayload(tool_name="demo-skill", tool_call_id="c1", start_time=now, status="started"),
            ),
            StructuredEvent(
                sequence=2,
                timestamp=now + 0.2,
                event_type=AgentEventType.TOOL_FAILURE.value,
                session_id=session_id,
                data=EventPayload(
                    tool_name="demo-skill",
                    tool_call_id="c1",
                    start_time=now,
                    end_time=now + 0.2,
                    duration_ms=200,
                    status="failed",
                    error="boom",
                ),
            ),
        ]
    )

    adapter = EventLogAdapter(backend)
    samples = await adapter.get_skill_executions("demo-skill", days=7)

    assert len(samples) == 1
    assert samples[0].success is False
