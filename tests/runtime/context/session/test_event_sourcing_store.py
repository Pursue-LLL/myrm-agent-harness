"""Unit tests for append-only event-sourcing session file store with corrupted tail auto-repair.

Verifies:
1. Normal sequential appending and loading of session event records.
2. Crash resilience: detecting and trimming half-written trailing records (JSONDecodeError).
3. Physical auto-repair rewrite: ensuring trailing line truncation prevents subsequent append concatenation errors.
4. Intermediate bad line tolerance.
5. Zero-lock stream-copy branching/forking with sequence caps.
6. Edge cases: non-existent file, empty file, whitespace lines.
"""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.runtime.context.session.event_sourcing_store import (
    EventSourcingSessionStore,
    SessionEventRecord,
    fork_session_by_stream_copy,
    load_session_events_with_auto_repair,
)


def test_session_event_record_serialization() -> None:
    rec = SessionEventRecord.create(
        seq=1,
        event_type="user_message",
        payload={"content": "Hello, agent!"},
        session_id="chat-123",
    )
    assert rec.seq == 1
    assert rec.event_type == "user_message"
    assert rec.session_id == "chat-123"

    json_str = rec.to_json()
    assert "\n" not in json_str
    data = json.loads(json_str)
    assert data["seq"] == 1
    assert data["payload"]["content"] == "Hello, agent!"


def test_normal_append_and_load(tmp_path: Path) -> None:
    session_file = tmp_path / "session_events.jsonl"
    store = EventSourcingSessionStore(session_file, session_id="test-session")

    r1 = store.append_event("user_message", {"text": "Step 1"})
    r2 = store.append_event("assistant_message", {"text": "Step 2"})
    r3 = store.append_event("tool_call", {"tool": "view_file"})

    assert r1.seq == 1
    assert r2.seq == 2
    assert r3.seq == 3

    records = store.load_all()
    assert len(records) == 3
    assert [r.seq for r in records] == [1, 2, 3]
    assert [r.event_type for r in records] == ["user_message", "assistant_message", "tool_call"]


def test_corrupted_trailing_line_auto_repair(tmp_path: Path) -> None:
    session_file = tmp_path / "corrupted_tail.jsonl"

    # Write two valid lines followed by a half-written truncated trailing line
    valid_1 = SessionEventRecord.create(1, "user", {"msg": "First"}).to_json()
    valid_2 = SessionEventRecord.create(2, "assistant", {"msg": "Second"}).to_json()
    corrupted_half_line = '{"seq": 3, "event_type": "tool_call", "payload": {"file": "/path/t'  # no closing brace/quote

    with session_file.open("w", encoding="utf-8") as f:
        f.write(f"{valid_1}\n{valid_2}\n{corrupted_half_line}")

    # Load with auto repair
    result = load_session_events_with_auto_repair(session_file, auto_repair_file=True)
    assert len(result.records) == 2
    assert result.corrupted_tail_trimmed is True
    assert result.trimmed_content == corrupted_half_line
    assert [r.seq for r in result.records] == [1, 2]

    # Verify physical file was repaired and rewritten cleanly with trailing newline
    repaired_content = session_file.read_text(encoding="utf-8")
    lines = [line.strip() for line in repaired_content.splitlines() if line.strip()]
    assert len(lines) == 2
    assert corrupted_half_line not in repaired_content
    assert repaired_content.endswith("\n")

    # Verify subsequent append works cleanly without concatenation
    store = EventSourcingSessionStore(session_file, session_id="repaired")
    r4 = store.append_event("tool_result", {"status": "ok"})
    assert r4.seq == 3  # next sequence from max existing seq (2 + 1)

    records_after = store.load_all()
    assert len(records_after) == 3
    assert [r.seq for r in records_after] == [1, 2, 3]


def test_skip_corrupted_middle_line(tmp_path: Path) -> None:
    session_file = tmp_path / "corrupted_middle.jsonl"

    valid_1 = SessionEventRecord.create(1, "user", {"msg": "First"}).to_json()
    bad_middle = "{not a valid json"
    valid_2 = SessionEventRecord.create(2, "assistant", {"msg": "Second"}).to_json()

    with session_file.open("w", encoding="utf-8") as f:
        f.write(f"{valid_1}\n{bad_middle}\n{valid_2}\n")

    result = load_session_events_with_auto_repair(session_file, auto_repair_file=False)
    assert len(result.records) == 2
    assert result.corrupted_tail_trimmed is False
    assert [r.seq for r in result.records] == [1, 2]


def test_fork_session_by_stream_copy(tmp_path: Path) -> None:
    src_file = tmp_path / "parent_session.jsonl"
    fork_file = tmp_path / "forked_session.jsonl"

    store = EventSourcingSessionStore(src_file, session_id="parent")
    for i in range(1, 6):
        store.append_event("turn_event", {"turn": i})

    # Fork up to seq 3
    copied_count = fork_session_by_stream_copy(src_file, fork_file, up_to_seq=3)
    assert copied_count == 3

    # Load forked branch
    forked_store = EventSourcingSessionStore(fork_file, session_id="child")
    forked_records = forked_store.load_all()
    assert len(forked_records) == 3
    assert [r.seq for r in forked_records] == [1, 2, 3]

    # Append to forked branch continues from 4
    r_new = forked_store.append_event("fork_diverge", {"info": "new branch"})
    assert r_new.seq == 4


def test_empty_and_non_existent_file(tmp_path: Path) -> None:
    non_existent = tmp_path / "non_existent.jsonl"
    res1 = load_session_events_with_auto_repair(non_existent)
    assert res1.records == []
    assert res1.corrupted_tail_trimmed is False

    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("   \n\n  ", encoding="utf-8")
    res2 = load_session_events_with_auto_repair(empty_file)
    assert res2.records == []
    assert res2.corrupted_tail_trimmed is False
