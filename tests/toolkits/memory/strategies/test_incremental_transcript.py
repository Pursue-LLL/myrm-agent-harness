"""Unit tests for IncrementalTranscriptParser and truncation protection."""

from __future__ import annotations

import io
import json

from myrm_agent_harness.toolkits.memory.strategies.incremental_transcript import (
    IncrementalTranscriptParser,
)


def test_parse_complete_stream() -> None:
    """Test parsing a complete JSONL transcript stream with paired turns."""
    line1 = json.dumps({
        "type": "user",
        "session_id": "sess-alpha",
        "content": "Why is redis pool exhausting?",
    }) + "\n"
    line2 = json.dumps({
        "type": "assistant",
        "content": [
            {"type": "text", "text": "The connections were not returned to pool."},
            {"type": "tool_use", "name": "check_redis_status"},
        ],
    }) + "\n"

    raw = (line1 + line2).encode("utf-8")
    stream = io.BytesIO(raw)

    chunk = IncrementalTranscriptParser.parse_stream(stream, start_offset=0)

    assert chunk.session_id == "sess-alpha"
    assert len(chunk.turns) == 1
    assert chunk.turns[0].user_content == "Why is redis pool exhausting?"
    assert "connections were not returned" in chunk.turns[0].assistant_content
    assert chunk.turns[0].tool_names == ["check_redis_status"]
    assert chunk.new_byte_offset == len(raw)
    assert not chunk.has_incomplete_tail
    assert chunk.consumed_lines == 2


def test_truncation_protection_and_resumption() -> None:
    """Test mid-write incomplete line is deferred and correctly resumed later."""
    line1 = json.dumps({"type": "user", "content": "Query 1"}) + "\n"
    line2_partial = '{"type": "assistant", "content": "Half writ'  # No trailing newline

    raw_partial = (line1 + line2_partial).encode("utf-8")
    stream1 = io.BytesIO(raw_partial)

    # First read
    chunk1 = IncrementalTranscriptParser.parse_stream(stream1, start_offset=0)
    assert chunk1.has_incomplete_tail is True
    assert chunk1.new_byte_offset == len(line1.encode("utf-8"))
    assert len(chunk1.turns) == 1
    assert chunk1.turns[0].user_content == "Query 1"

    # Second read after external agent completes line2
    line2_completed = json.dumps({"type": "assistant", "content": "Half written now complete."}) + "\n"
    raw_resumed = (line1 + line2_completed).encode("utf-8")
    stream2 = io.BytesIO(raw_resumed)

    chunk2 = IncrementalTranscriptParser.parse_stream(stream2, start_offset=chunk1.new_byte_offset)
    assert chunk2.has_incomplete_tail is False
    assert chunk2.new_byte_offset == len(raw_resumed)
    assert len(chunk2.turns) == 1
    assert "Half written now complete." in chunk2.turns[0].assistant_content


def test_malformed_jsonl_tolerance() -> None:
    """Malformed JSON line should be skipped with warning and not crash parser."""
    valid_line = json.dumps({"type": "user", "content": "Hello"}) + "\n"
    corrupt_line = "Not a json line {[[{\n"

    raw = (corrupt_line + valid_line).encode("utf-8")
    chunk = IncrementalTranscriptParser.parse_stream(io.BytesIO(raw))

    assert "invalid_json_line_skipped" in chunk.warnings
    assert len(chunk.turns) == 1
    assert chunk.turns[0].user_content == "Hello"
