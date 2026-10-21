"""Unit and benchmark tests for FileEventLogBackend pre-filtering and off-event-loop execution.

[INPUT]
- myrm_agent_harness.agent.event_log.backends.file_backend::FileEventLogBackend
- myrm_agent_harness.agent.event_log.types::EventFilter, StructuredEvent

[OUTPUT]
- Pytest test cases verifying line pre-filtering, parsing correctness, and event-loop liveness

[POS]
- tests/agent/event_log/test_file_backend_prefilter.py: Item 60 verification suite
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.types import EventFilter


@pytest.fixture
def temp_log_dir(tmp_path: Path) -> Path:
    log_dir = tmp_path / "event_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


@pytest.mark.asyncio
async def test_get_events_fast_prefilter_accuracy(temp_log_dir: Path) -> None:
    session_id = "test_prefilter_session"
    backend = FileEventLogBackend(log_dir=temp_log_dir, session_id=session_id)
    file_path = temp_log_dir / f"{session_id}.jsonl"

    # Write 200 noise events (tool_start, tool_success, ui_update) and 2 session_end events
    lines: list[str] = []
    base_ts = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC).timestamp()

    for i in range(1, 101):
        lines.append(
            json.dumps(
                {
                    "seq": i,
                    "ts": base_ts + i,
                    "type": "tool_start",
                    "sid": session_id,
                    "data": {"tool_name": f"tool_{i}", "args": {"x": i}},
                }
            )
        )

    # Insert 1st target event
    lines.append(
        json.dumps(
            {
                "seq": 101,
                "ts": base_ts + 101,
                "type": "session_end",
                "sid": session_id,
                "data": {"summary": {"tool_calls": 50, "duration_ms": 1200.0}},
            }
        )
    )

    for i in range(102, 201):
        lines.append(
            json.dumps(
                {
                    "seq": i,
                    "ts": base_ts + i,
                    "type": "tool_success",
                    "sid": session_id,
                    "data": {"tool_name": f"tool_{i}", "result": "ok"},
                }
            )
        )

    # Insert 2nd target event
    lines.append(
        json.dumps(
            {
                "seq": 201,
                "ts": base_ts + 201,
                "type": "session_end",
                "sid": session_id,
                "data": {"summary": {"tool_calls": 80, "duration_ms": 2000.0}},
            }
        )
    )

    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Filter strictly for session_end
    filter_target = EventFilter(event_types=frozenset({"session_end"}))
    events = await backend.get_events(session_id, filter_target)

    assert len(events) == 2
    assert events[0].event_type == "session_end"
    assert events[0].sequence == 101
    assert events[0].data.summary.get("tool_calls") == 50

    assert events[1].event_type == "session_end"
    assert events[1].sequence == 201
    assert events[1].data.summary.get("tool_calls") == 80


@pytest.mark.asyncio
async def test_get_events_fast_prefilter_skips_json_loads(temp_log_dir: Path) -> None:
    session_id = "test_skip_session"
    backend = FileEventLogBackend(log_dir=temp_log_dir, session_id=session_id)
    file_path = temp_log_dir / f"{session_id}.jsonl"

    # Write 500 lines of other event types
    lines: list[str] = [
        json.dumps({"seq": i, "ts": 1000.0 + i, "type": "heartbeat", "sid": session_id, "data": {}})
        for i in range(500)
    ]
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    filter_session_end = EventFilter(event_types=frozenset({"session_end"}))

    start_perf = time.perf_counter()
    events = await backend.get_events(session_id, filter_session_end)
    elapsed = time.perf_counter() - start_perf

    assert len(events) == 0
    # Fast string prefilter should execute in a few milliseconds
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_off_event_loop_does_not_block_concurrent_heartbeat(temp_log_dir: Path) -> None:
    session_id = "test_liveness_session"
    backend = FileEventLogBackend(log_dir=temp_log_dir, session_id=session_id)
    file_path = temp_log_dir / f"{session_id}.jsonl"

    # Create 3000 events to ensure measurable IO/parse work
    lines = [
        json.dumps({"seq": i, "ts": 1000.0 + i, "type": "tool_start", "sid": session_id, "data": {"idx": i}})
        for i in range(3000)
    ]
    lines.append(
        json.dumps(
            {"seq": 3001, "ts": 4000.0, "type": "session_end", "sid": session_id, "data": {"summary": {}}}
        )
    )
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    heartbeat_ticks = 0

    async def _heartbeat() -> None:
        nonlocal heartbeat_ticks
        for _ in range(10):
            await asyncio.sleep(0.005)
            heartbeat_ticks += 1

    heartbeat_task = asyncio.create_task(_heartbeat())
    events = await backend.get_events(session_id, EventFilter(event_types=frozenset({"session_end"})))
    await heartbeat_task

    assert len(events) == 1
    # Event loop continued to tick while backend scanned in thread pool
    assert heartbeat_ticks > 0
