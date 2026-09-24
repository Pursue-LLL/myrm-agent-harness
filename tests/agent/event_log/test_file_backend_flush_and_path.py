"""Tests for FileEventLogBackend flush barrier and get_session_log_path."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.protocols import (
    EventLogBackend,
    FlushableEventLogBackend,
)
from myrm_agent_harness.agent.event_log.types import EventPayload, StructuredEvent


@pytest.mark.asyncio
async def test_file_backend_protocol_conformance(tmp_path: Path) -> None:
    backend = FileEventLogBackend(log_dir=tmp_path, session_id="sess-proto")
    assert isinstance(backend, EventLogBackend)
    assert isinstance(backend, FlushableEventLogBackend)


@pytest.mark.asyncio
async def test_file_backend_flush_and_path(tmp_path: Path) -> None:
    session_id = "sess-123"
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=session_id)

    # Initial state: file does not exist yet
    assert backend.get_session_log_path(session_id) is None

    # Append an event
    event = StructuredEvent(
        sequence=1,
        timestamp=time.time(),
        event_type="test_event",
        session_id=session_id,
        data=EventPayload(content="test content"),
    )
    await backend.append([event])

    # Durability flush barrier
    await backend.flush()

    # Path now exists and points to the raw jsonl
    path = backend.get_session_log_path(session_id)
    assert path is not None
    assert path.exists()
    assert path.name == f"{session_id}.jsonl"

    content = path.read_text(encoding="utf-8")
    assert "test_event" in content
    assert "test content" in content

    # Close flushes cleanly
    await backend.close()
