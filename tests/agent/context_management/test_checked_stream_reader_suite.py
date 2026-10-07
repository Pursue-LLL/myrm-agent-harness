"""Unit tests for Checked Session Reply Stream Readers and Anti-Slop Governance Suite.

Verifies raw template tag purging, excessive newline collapsing, stream frame sequence continuity,
gap auto-healing state transitions, terminal DONE/ERROR guards, and global streaming telemetry.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    AntiSlopFilter,
    AntiSlopFilterResult,
    AntiSlopViolationKind,
    CheckedSessionReplyStreamReader,
    CheckedSessionReplyStreamReadersAndAntiSlopGovernanceSuite,
    StreamChunkFrame,
    StreamChunkKind,
    StreamReaderMetrics,
    StreamReaderState,
)


def test_anti_slop_filter_scrubbing_and_validation() -> None:
    """Verify anti-slop cleaning of raw template tags, excessive newlines, and empty payloads."""
    filter_engine = AntiSlopFilter()

    # 1. Clean raw template tag bleed-through
    frame_raw_tags = StreamChunkFrame(
        sequence_id=0,
        kind=StreamChunkKind.TEXT,
        content="<|im_start|>assistant\nHello world!</think>",
        session_id="test-sess",
    )
    res_tags = filter_engine.filter_chunk(frame_raw_tags)
    assert res_tags.is_valid
    assert "<|im_start|>" not in res_tags.cleaned_content
    assert "</think>" not in res_tags.cleaned_content
    assert "Hello world!" in res_tags.cleaned_content
    assert AntiSlopViolationKind.RAW_TEMPLATE_TAG in res_tags.violations

    # 2. Collapse excessive blank lines
    frame_newlines = StreamChunkFrame(
        sequence_id=1,
        kind=StreamChunkKind.TEXT,
        content="Paragraph 1\n\n\n\n\nParagraph 2",
        session_id="test-sess",
    )
    res_newlines = filter_engine.filter_chunk(frame_newlines)
    assert res_newlines.cleaned_content == "Paragraph 1\n\nParagraph 2"
    assert AntiSlopViolationKind.EXCESSIVE_NEWLINES in res_newlines.violations

    # 3. Empty text payload rejection
    frame_empty = StreamChunkFrame(
        sequence_id=2,
        kind=StreamChunkKind.TEXT,
        content="",
        session_id="test-sess",
    )
    res_empty = filter_engine.filter_chunk(frame_empty)
    assert not res_empty.is_valid
    assert AntiSlopViolationKind.EMPTY_PAYLOAD in res_empty.violations

    # 4. Heartbeat control frame pass-through
    frame_hb = StreamChunkFrame(
        sequence_id=3,
        kind=StreamChunkKind.HEARTBEAT,
        content="ping",
        session_id="test-sess",
    )
    res_hb = filter_engine.filter_chunk(frame_hb)
    assert res_hb.is_valid
    assert len(res_hb.violations) == 0


def test_checked_reply_reader_sequence_continuity_and_healing() -> None:
    """Verify reader state transitions, frame continuity validation, and automatic gap healing."""
    # 1. Normal continuous stream with auto healing enabled
    reader = CheckedSessionReplyStreamReader(session_id="sess-stream-1", auto_heal_sequence_gaps=True)
    assert reader.state == StreamReaderState.IDLE

    f0 = StreamChunkFrame(sequence_id=0, kind=StreamChunkKind.TEXT, content="Part 1 ", session_id="sess-stream-1")
    f1 = StreamChunkFrame(sequence_id=1, kind=StreamChunkKind.TEXT, content="Part 2 ", session_id="sess-stream-1")
    out0 = reader.consume_frame(f0)
    out1 = reader.consume_frame(f1)
    assert out0 is not None and out1 is not None
    assert reader.state == StreamReaderState.STREAMING

    # 2. Introduce a gap: jump to sequence 4
    f_gap = StreamChunkFrame(sequence_id=4, kind=StreamChunkKind.TEXT, content="Part 3 ", session_id="sess-stream-1")
    out_gap = reader.consume_frame(f_gap)
    assert out_gap is not None
    assert reader.state == StreamReaderState.STREAMING
    assert reader.expected_sequence_id == 5

    # 3. Complete stream with DONE frame
    f_done = StreamChunkFrame(sequence_id=5, kind=StreamChunkKind.DONE, content="", session_id="sess-stream-1")
    reader.consume_frame(f_done)
    assert reader.state == StreamReaderState.COMPLETED
    assert reader.get_full_buffered_content() == "Part 1 Part 2 Part 3 "

    metrics = reader.get_metrics()
    assert metrics.frames_processed == 4
    assert metrics.healed_gaps == 1
    assert metrics.total_characters_delivered == len("Part 1 Part 2 Part 3 ")

    # 4. Strict reader without auto healing breaks on gap
    strict_reader = CheckedSessionReplyStreamReader(session_id="sess-strict", auto_heal_sequence_gaps=False)
    strict_reader.consume_frame(f0)
    out_broken = strict_reader.consume_frame(f_gap)  # Gap jumps from 1 to 4
    assert out_broken is None
    assert strict_reader.state == StreamReaderState.BROKEN


def test_checked_stream_suite_batch_processing_and_telemetry() -> None:
    """Verify master suite batch processing, stand-alone auditing, and telemetry."""
    suite = CheckedSessionReplyStreamReadersAndAntiSlopGovernanceSuite()

    frames = [
        StreamChunkFrame(sequence_id=0, kind=StreamChunkKind.TEXT, content="Line 1\n", session_id="batch-sess"),
        StreamChunkFrame(sequence_id=1, kind=StreamChunkKind.TEXT, content="Line 2\n", session_id="batch-sess"),
        StreamChunkFrame(sequence_id=2, kind=StreamChunkKind.DONE, content="", session_id="batch-sess"),
    ]

    buffered_text, metrics, final_state = suite.process_stream(
        session_id="batch-sess",
        frames=frames,
        auto_heal=True,
    )
    assert buffered_text == "Line 1\nLine 2\n"
    assert final_state == StreamReaderState.COMPLETED
    assert metrics.frames_processed == 3

    # Stand-alone slop audit
    audit_res = suite.audit_content_for_slop("[INST] System instructions [/INST]\nHere is the answer.")
    assert audit_res.is_valid
    assert "[INST]" not in audit_res.cleaned_content
    assert AntiSlopViolationKind.RAW_TEMPLATE_TAG in audit_res.violations

    # Global telemetry aggregation
    telemetry = suite.get_global_telemetry()
    assert telemetry["total_streams_completed"] == 1
    assert telemetry["total_frames_processed"] == 3
    assert telemetry["total_characters_delivered"] == len("Line 1\nLine 2\n")
