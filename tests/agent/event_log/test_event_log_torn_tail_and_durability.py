"""Unit tests for EventLog torn tail self-repair, atomic probing, and durability.

Verifies:
1. inspect_tail accurately detects clean vs torn tails using O(1) reverse seek.
2. repair_torn_tail atomically truncates uncommitted garbage and propagates failure.
3. get_events skips uncommitted unterminated final lines on read without errors.
4. append automatically repairs torn tails before writing, preventing cross-line corruption.
5. get_latest_custom_state safely skips torn tail fragments.
6. loop_write_all defends against short writes and interrupted syscalls.
7. Concurrent appends remain consistent under file lock protection.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.durable_atomic_writer import DurableLogWriter, loop_write_all
from myrm_agent_harness.agent.event_log.torn_tail_repairer import (
    TailRepairError,
    inspect_tail,
    repair_torn_tail,
)
from myrm_agent_harness.agent.event_log.types import EventPayload, StructuredEvent


def _make_test_event(seq: int, sid: str = "sess-1", etype: str = "custom") -> StructuredEvent:
    return StructuredEvent(
        sequence=seq,
        timestamp=1000.0 + seq,
        event_type=etype,
        session_id=sid,
        data=EventPayload(payload_val=f"val_{seq}"),
    )


def test_inspect_tail_detects_clean_file_and_empty_file(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.jsonl"
    empty_file.touch()
    res_empty = inspect_tail(empty_file)
    assert not res_empty.has_torn_tail
    assert res_empty.file_size == 0
    assert res_empty.clean_size == 0
    assert res_empty.torn_bytes == 0

    clean_file = tmp_path / "clean.jsonl"
    clean_content = b'{"seq":1,"type":"start"}\n{"seq":2,"type":"end"}\n'
    clean_file.write_bytes(clean_content)
    res_clean = inspect_tail(clean_file)
    assert not res_clean.has_torn_tail
    assert res_clean.file_size == len(clean_content)
    assert res_clean.clean_size == len(clean_content)
    assert res_clean.torn_bytes == 0

    missing_file = tmp_path / "missing.jsonl"
    res_missing = inspect_tail(missing_file)
    assert not res_missing.has_torn_tail
    assert res_missing.file_size == 0


def test_inspect_tail_detects_unterminated_final_line(tmp_path: Path) -> None:
    torn_file = tmp_path / "torn.jsonl"
    valid_prefix = b'{"seq":1,"type":"start"}\n{"seq":2,"type":"tool"}\n'
    torn_fragment = b'{"seq":3,"type":"crash_mid_wr'
    torn_file.write_bytes(valid_prefix + torn_fragment)

    res = inspect_tail(torn_file)
    assert res.has_torn_tail
    assert res.file_size == len(valid_prefix) + len(torn_fragment)
    assert res.clean_size == len(valid_prefix)
    assert res.torn_bytes == len(torn_fragment)


def test_repair_torn_tail_atomically_truncates_garbage(tmp_path: Path) -> None:
    torn_file = tmp_path / "torn_repair.jsonl"
    valid_prefix = b'{"seq":1}\n{"seq":2}\n'
    torn_fragment = b'{"seq":3,"uncommitted_corrupt'
    torn_file.write_bytes(valid_prefix + torn_fragment)

    report = repair_torn_tail(torn_file)
    assert report.repaired
    assert report.truncated_bytes == len(torn_fragment)
    assert report.repaired_size == len(valid_prefix)
    assert torn_file.read_bytes() == valid_prefix

    # Second repair should be a no-op
    report_noop = repair_torn_tail(torn_file)
    assert not report_noop.repaired
    assert report_noop.truncated_bytes == 0
    assert torn_file.read_bytes() == valid_prefix


def test_repair_torn_tail_propagates_failure_when_io_error(tmp_path: Path) -> None:
    torn_file = tmp_path / "unwritable.jsonl"
    torn_file.write_bytes(b'{"seq":1}\n{"seq":2,"torn')

    with patch("os.fsync", side_effect=OSError("Disk sync failed")):
        with pytest.raises(TailRepairError) as exc_info:
            repair_torn_tail(torn_file)
        assert "Failed to truncate torn tail" in str(exc_info.value)
        assert "Disk sync failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_events_skips_unterminated_final_line_on_read(tmp_path: Path) -> None:
    sid = "read-test"
    log_file = tmp_path / f"{sid}.jsonl"

    ev1 = _make_test_event(1, sid, "tool_start")
    ev2 = _make_test_event(2, sid, "tool_end")
    line1 = json.dumps(ev1.to_dict()) + "\n"
    line2 = json.dumps(ev2.to_dict()) + "\n"
    uncommitted = '{"seq":3,"type":"crash'
    log_file.write_text(line1 + line2 + uncommitted, encoding="utf-8")

    backend = FileEventLogBackend(tmp_path, sid)
    events = await backend.get_events(sid)

    # ev3 is uncommitted and unterminated, so get_events drops it safely
    assert len(events) == 2
    assert events[0].sequence == 1
    assert events[1].sequence == 2


@pytest.mark.asyncio
async def test_append_automatically_repairs_torn_tail_before_writing(tmp_path: Path) -> None:
    sid = "crash-restart-test"
    log_file = tmp_path / f"{sid}.jsonl"

    ev1 = _make_test_event(1, sid, "tool_start")
    ev2 = _make_test_event(2, sid, "tool_end")
    line1 = json.dumps(ev1.to_dict()) + "\n"
    line2 = json.dumps(ev2.to_dict()) + "\n"
    torn_garbage = '{"seq":3,"ty'
    log_file.write_text(line1 + line2 + torn_garbage, encoding="utf-8")

    backend = FileEventLogBackend(tmp_path, sid)
    ev3 = _make_test_event(3, sid, "agent_finish")
    await backend.append([ev3])

    # Verify log content on disk: no spliced line like '{"seq":3,"ty{"seq":3...'
    content = log_file.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    assert len(lines) == 3

    parsed_events = await backend.get_events(sid)
    assert len(parsed_events) == 3
    assert parsed_events[0].sequence == 1
    assert parsed_events[1].sequence == 2
    assert parsed_events[2].sequence == 3
    assert parsed_events[2].event_type == "agent_finish"


@pytest.mark.asyncio
async def test_get_latest_custom_state_skips_uncommitted_torn_tail(tmp_path: Path) -> None:
    sid = "custom-state-test"
    log_file = tmp_path / f"{sid}.jsonl"

    rec1 = {
        "seq": 1,
        "ts": 100.0,
        "type": "custom",
        "sid": sid,
        "data": {"custom_type": "profile", "state": {"level": 1}},
    }
    rec2 = {
        "seq": 2,
        "ts": 101.0,
        "type": "custom",
        "sid": sid,
        "data": {"custom_type": "profile", "state": {"level": 2}},
    }
    line1 = json.dumps(rec1) + "\n"
    line2 = json.dumps(rec2) + "\n"
    torn_line = '{"seq":3,"type":"custom","data":{"custom_type":"profile","state":'
    log_file.write_text(line1 + line2 + torn_line, encoding="utf-8")

    backend = FileEventLogBackend(tmp_path, sid)
    state = await backend.get_latest_custom_state(sid, custom_type="profile")
    assert state == {"level": 2}


def test_loop_write_all_handles_short_writes(tmp_path: Path) -> None:
    target_file = tmp_path / "short_write.dat"
    payload = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 100

    fd = os.open(target_file, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        real_write = os.write
        write_call_count = 0

        def flaky_write(d: int, b: bytes) -> int:
            nonlocal write_call_count
            write_call_count += 1
            if write_call_count == 2:
                raise InterruptedError("Syscall interrupted")
            # Force short write of max 17 bytes
            chunk = min(len(b), 17)
            return real_write(d, b[:chunk])

        with patch("os.write", side_effect=flaky_write):
            written = loop_write_all(fd, payload)

        assert written == len(payload)
        assert write_call_count > 10
    finally:
        os.close(fd)

    assert target_file.read_bytes() == payload


@pytest.mark.asyncio
async def test_durable_log_writer_concurrent_appends(tmp_path: Path) -> None:
    log_file = tmp_path / "concurrent_appends.jsonl"
    writer = DurableLogWriter(log_file, durable=False, use_file_lock=True)

    async def worker(worker_id: int, count: int) -> None:
        for i in range(count):
            line = json.dumps({"worker": worker_id, "i": i}) + "\n"
            await asyncio.to_thread(writer.append_lines, [line])

    tasks = [asyncio.create_task(worker(w, 20)) for w in range(5)]
    await asyncio.gather(*tasks)

    content = log_file.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    assert len(lines) == 100
    for line in lines:
        data = json.loads(line)
        assert "worker" in data
        assert "i" in data
