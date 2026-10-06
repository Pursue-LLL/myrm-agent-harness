"""Tests for 384K Extreme Long Output Streaming and Chunk Memory Governor."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.extreme_streaming_governor import (
    CursorExpiredError,
    ExtremeStreamingGovernor,
    StreamResumeCursor,
)


def test_stream_chunk_push_and_sequence_monotonicity():
    governor = ExtremeStreamingGovernor(stream_id="stream-test-1", buffer_capacity=100)

    c0 = governor.push_chunk("Hello")
    c1 = governor.push_chunk(" world!")
    c2 = governor.push_chunk("", is_terminal=True)

    assert c0.sequence_id == 0
    assert c0.byte_offset == 0
    assert c0.content == "Hello"
    assert c0.is_terminal is False

    assert c1.sequence_id == 1
    assert c1.byte_offset == len(b"Hello")
    assert c1.content == " world!"
    assert c1.is_terminal is False

    assert c2.sequence_id == 2
    assert c2.byte_offset == len(b"Hello world!")
    assert c2.is_terminal is True

    stats = governor.get_governor_stats()
    assert stats.total_chunks_produced == 3
    assert stats.total_chars_produced == len("Hello world!")


def test_auto_artifact_offload_threshold_trigger():
    # 50 bytes threshold
    governor = ExtremeStreamingGovernor(
        stream_id="stream-large-doc",
        offload_byte_threshold=50,
    )

    assert governor.is_offloaded is False
    assert governor.artifact_id is None

    # Push 30 bytes
    governor.push_chunk("a" * 30)
    assert governor.is_offloaded is False

    # Push another 30 bytes (total 60 bytes >= 50)
    governor.push_chunk("b" * 30)
    assert governor.is_offloaded is True
    assert governor.artifact_id == "art-stream-stream-large-doc"

    status = governor.get_offload_status()
    assert status.is_offloaded is True
    assert status.artifact_id == "art-stream-stream-large-doc"
    assert status.total_bytes_streamed == 60


def test_lightweight_summary_generation():
    governor = ExtremeStreamingGovernor(
        stream_id="stream-summary",
        offload_byte_threshold=40,
    )

    # 1. Under threshold
    governor.push_chunk("Short message.")
    assert governor.get_lightweight_summary(preview_chars=50) == "Short message."

    # 2. Exceed threshold to trigger offload
    governor.push_chunk(" Long tail content that exceeds the offloading boundary.")
    summary = governor.get_lightweight_summary(preview_chars=15)

    assert summary.startswith("Short message. ")
    assert "[... Output stream offloaded to Artifact 'art-stream-stream-summary'" in summary


def test_ring_buffer_bounded_capacity_and_eviction():
    # Keep only 3 chunks in memory ring buffer
    governor = ExtremeStreamingGovernor(stream_id="stream-ring", buffer_capacity=3)

    for i in range(5):
        governor.push_chunk(f"chunk-{i}")

    stats = governor.get_governor_stats()
    assert stats.total_chunks_produced == 5
    assert stats.buffered_chunks_count == 3
    assert stats.evicted_chunks_count == 2

    # Ring buffer now holds sequences 2, 3, 4
    cursor = StreamResumeCursor(stream_id="stream-ring", last_acked_sequence_id=1, last_acked_byte_offset=0)
    replayed = governor.get_chunks_since(cursor)
    assert len(replayed) == 3
    assert [c.sequence_id for c in replayed] == [2, 3, 4]


def test_idempotent_reconnect_resume_from_cursor():
    governor = ExtremeStreamingGovernor(stream_id="stream-resume", buffer_capacity=10)

    for i in range(4):
        governor.push_chunk(f"delta-{i}")

    # Client was disconnected after acknowledging sequence 1
    cursor = StreamResumeCursor(
        stream_id="stream-resume",
        last_acked_sequence_id=1,
        last_acked_byte_offset=100,
    )
    resumed = governor.get_chunks_since(cursor)

    assert len(resumed) == 2
    assert [c.sequence_id for c in resumed] == [2, 3]

    # Client already up to date
    cursor_latest = StreamResumeCursor(
        stream_id="stream-resume",
        last_acked_sequence_id=3,
        last_acked_byte_offset=200,
    )
    assert governor.get_chunks_since(cursor_latest) == ()


def test_cursor_expired_error_when_evicted():
    governor = ExtremeStreamingGovernor(stream_id="stream-evict", buffer_capacity=2)

    for i in range(5):
        governor.push_chunk(f"c-{i}")

    # Currently holds sequences 3 and 4
    # Client requests from sequence 0 (evicted long ago)
    expired_cursor = StreamResumeCursor(
        stream_id="stream-evict",
        last_acked_sequence_id=0,
        last_acked_byte_offset=0,
    )
    with pytest.raises(CursorExpiredError, match="Requested sequence 0 expired"):
        governor.get_chunks_since(expired_cursor)


def test_stream_id_mismatch_error():
    governor = ExtremeStreamingGovernor(stream_id="stream-valid")
    mismatched_cursor = StreamResumeCursor(
        stream_id="stream-foreign",
        last_acked_sequence_id=0,
        last_acked_byte_offset=0,
    )
    with pytest.raises(ValueError, match="does not match governor"):
        governor.get_chunks_since(mismatched_cursor)
