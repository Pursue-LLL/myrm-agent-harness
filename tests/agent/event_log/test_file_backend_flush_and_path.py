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


@pytest.mark.asyncio
async def test_file_backend_validation_and_empty_append(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_jsonl_line_bytes must be at least 64"):
        FileEventLogBackend(log_dir=tmp_path, session_id="s", max_jsonl_line_bytes=32)

    backend = FileEventLogBackend(log_dir=tmp_path, session_id="s")
    # Empty append is a no-op
    await backend.append([])
    assert backend.get_session_log_path("s") is None


@pytest.mark.asyncio
async def test_file_backend_get_all_session_ids(tmp_path: Path) -> None:
    non_existent = tmp_path / "not_there"
    backend = FileEventLogBackend(log_dir=non_existent, session_id="s1")
    assert await backend.get_all_session_ids() == []

    # Write files for two sessions
    b1 = FileEventLogBackend(log_dir=tmp_path, session_id="beta")
    b2 = FileEventLogBackend(log_dir=tmp_path, session_id="alpha")
    now = time.time()
    await b1.append([
        StructuredEvent(
            sequence=1,
            timestamp=now,
            event_type="init",
            session_id="beta",
            data=EventPayload(),
        )
    ])
    await b2.append([
        StructuredEvent(
            sequence=1,
            timestamp=now,
            event_type="init",
            session_id="alpha",
            data=EventPayload(),
        )
    ])

    session_ids = await b1.get_all_session_ids()
    assert session_ids == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_file_backend_get_events_filtering_and_malformed(tmp_path: Path) -> None:
    session_id = "filter-sess"
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=session_id)
    t0 = 100.0
    events = [
        StructuredEvent(
            sequence=1,
            timestamp=t0,
            event_type="start",
            session_id=session_id,
            data=EventPayload(val=1),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=t0 + 10,
            event_type="middle",
            session_id=session_id,
            data=EventPayload(val=2),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=t0 + 20,
            event_type="end",
            session_id=session_id,
            data=EventPayload(val=3),
        ),
    ]
    await backend.append(events)

    # Inject an empty line and a malformed JSON line into the file
    path = backend.get_session_log_path(session_id)
    assert path is not None
    original_text = path.read_text(encoding="utf-8")
    corrupted_text = original_text + "\n   \n{invalid json}\n"
    path.write_text(corrupted_text, encoding="utf-8")

    from myrm_agent_harness.agent.event_log.types import EventFilter

    # Filter by start_time and end_time
    filtered = await backend.get_events(
        session_id,
        EventFilter(start_time=t0 + 5, end_time=t0 + 15),
    )
    assert len(filtered) == 1
    assert filtered[0].sequence == 2
    assert filtered[0].event_type == "middle"


@pytest.mark.asyncio
async def test_file_backend_line_bytes_downgrades(tmp_path: Path) -> None:
    # Test tight and tiny downgrade when payload exceeds max_jsonl_line_bytes
    backend = FileEventLogBackend(
        log_dir=tmp_path,
        session_id="downgrade-sess",
        max_jsonl_line_bytes=120,
    )
    huge_data = {"key": "x" * 200}
    event = StructuredEvent(
        sequence=1,
        timestamp=time.time(),
        event_type="large_payload",
        session_id="downgrade-sess",
        data=EventPayload(**huge_data),
    )
    await backend.append([event])
    await backend.flush()

    events = await backend.get_events("downgrade-sess")
    assert len(events) == 1
    assert events[0].sequence == 1


@pytest.mark.asyncio
async def test_file_backend_cleanup_old_logs(tmp_path: Path) -> None:
    non_existent = tmp_path / "cleanup_none"
    b_none = FileEventLogBackend(log_dir=non_existent, session_id="none")
    assert await b_none.cleanup_old_logs() == 0

    log_dir = tmp_path / "logs"
    backend = FileEventLogBackend(log_dir=log_dir, session_id="old-sess", retention_days=1)
    await backend.append([
        StructuredEvent(
            sequence=1,
            timestamp=time.time(),
            event_type="test",
            session_id="old-sess",
            data=EventPayload(),
        )
    ])
    log_path = backend.get_session_log_path("old-sess")
    assert log_path is not None

    # Artificially set mtime to 2 days ago
    two_days_ago = time.time() - (2 * 86400)
    import os
    os.utime(log_path, (two_days_ago, two_days_ago))

    deleted = await backend.cleanup_old_logs()
    assert deleted == 1
    assert not log_path.exists()

