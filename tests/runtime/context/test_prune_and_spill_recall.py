"""Tests for Prune and Spill with Zero-Overhead Offset Recall Loop (Pi Harness v2 Item 22)."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.runtime.context.prune_and_spill_recall import (
    GrepRecallResult,
    OffsetRecallResult,
    PruneAndSpillConfig,
    PruneAndSpillRecallEngine,
    PruneAndSpillResult,
    SpillMetadata,
)


def test_within_threshold_no_spill(tmp_path: Path) -> None:
    """Test short output within inline limits is not spilled."""
    engine = PruneAndSpillRecallEngine(
        PruneAndSpillConfig(
            max_inline_chars=1000,
            max_inline_lines=50,
            storage_dir=tmp_path,
        )
    )

    short_text = "Line 1: Status OK\nLine 2: All tests passed\n"
    res: PruneAndSpillResult = engine.prune_and_spill(
        short_text,
        tool_name="test_runner",
        chat_id="chat-001",
    )

    assert res.was_spilled is False
    assert res.content == short_text
    assert res.metadata is None


def test_exceeds_threshold_spills_100_percent_and_inserts_recall_marker(tmp_path: Path) -> None:
    """Test large output is 100% written to disk, and context contains zero-overhead marker."""
    engine = PruneAndSpillRecallEngine(
        PruneAndSpillConfig(
            max_inline_chars=500,
            max_inline_lines=40,
            head_lines=10,
            tail_lines=10,
            storage_dir=tmp_path,
        )
    )

    # Generate 100 lines of log, with an elusive error hidden in the middle (line 50)
    lines: list[str] = [f"Log record {i}: Normal operation" for i in range(1, 101)]
    lines[49] = "Log record 50: CRITICAL_ERROR - database connection pool exhausted"
    raw_content = "\n".join(lines) + "\n"

    res = engine.prune_and_spill(
        raw_content,
        tool_name="db_benchmark",
        call_id="call-db-99",
        chat_id="session-spill-test",
    )

    assert res.was_spilled is True
    assert res.metadata is not None
    meta: SpillMetadata = res.metadata

    # 1. 100% raw content preserved on disk
    spilled_file = Path(meta.file_path)
    assert spilled_file.exists()
    assert spilled_file.read_text(encoding="utf-8") == raw_content
    assert meta.total_lines == 100

    # 2. Omitted middle calculation
    assert meta.omitted_start_line == 11
    assert meta.omitted_end_line == 90
    assert meta.omitted_line_count == 80

    # 3. Inline context verification
    compact = res.content
    assert "ZERO-OVERHEAD RECALL MARKER" in compact
    assert f"Spill ID: {meta.spill_id}" in compact
    assert f"Full Raw File: {meta.file_path}" in compact
    assert "Omitted Middle: 80 lines [L11 - L90]" in compact
    assert "Recall Instruction:" in compact

    # Head and tail lines are preserved in inline context
    assert "Log record 1: Normal operation" in compact
    assert "Log record 10: Normal operation" in compact
    assert "Log record 91: Normal operation" in compact
    assert "Log record 100: Normal operation" in compact

    # Crucial: the middle error is pruned from inline context to preserve tokens
    assert "Log record 50: CRITICAL_ERROR" not in compact


def test_offset_recall_by_lines(tmp_path: Path) -> None:
    """Test targeted streaming line offset recall reads middle sections on demand."""
    engine = PruneAndSpillRecallEngine(
        PruneAndSpillConfig(
            max_inline_chars=200,
            max_inline_lines=15,
            head_lines=5,
            tail_lines=5,
            storage_dir=tmp_path,
        )
    )

    # 60 lines, error on line 35
    lines: list[str] = [f"Step {i}: executing step details" for i in range(1, 61)]
    lines[34] = "Step 35: FATAL_KERNEL_PANIC: memory access violation at 0xdeadbeef"
    raw_content = "\n".join(lines) + "\n"

    res = engine.prune_and_spill(raw_content, tool_name="kernel_trace", chat_id="chat-recall")
    assert res.metadata is not None
    spill_id = res.metadata.spill_id

    # Model uses recall_by_lines to read around line 35
    recall_res: OffsetRecallResult = engine.recall_by_lines(
        spill_id,
        start_line=34,
        max_lines=3,
    )

    assert recall_res.start_line == 34
    assert recall_res.returned_lines == 3
    assert recall_res.total_lines == 60
    assert recall_res.has_more is True

    # Confirm the exact error line is recovered
    assert "Step 34: executing step details" in recall_res.content
    assert "Step 35: FATAL_KERNEL_PANIC" in recall_res.content
    assert "Step 36: executing step details" in recall_res.content


def test_offset_recall_by_bytes(tmp_path: Path) -> None:
    """Test targeted byte offset recall reads exact slices."""
    engine = PruneAndSpillRecallEngine(
        PruneAndSpillConfig(
            max_inline_chars=100,
            max_inline_lines=5,
            head_lines=2,
            tail_lines=2,
            storage_dir=tmp_path,
        )
    )

    raw_text = "ABCDEFGHIJ\nKLMNOPQRST\nUVWXYZ0123\n456789ABCD\nEFGHIJKLMN\nOPQRSTUVWX\n"
    res = engine.prune_and_spill(raw_text, chat_id="chat-bytes")
    assert res.metadata is not None

    # Read bytes starting at byte offset 11 (second line "KLMNOPQRST\n")
    slice_data = engine.recall_by_bytes(res.metadata.spill_id, start_byte=11, max_bytes=10)
    assert slice_data == "KLMNOPQRST"


def test_grep_evicted_matches(tmp_path: Path) -> None:
    """Test fast regex scanning over spilled file to pinpoint error coordinates."""
    engine = PruneAndSpillRecallEngine(
        PruneAndSpillConfig(
            max_inline_chars=100,
            max_inline_lines=5,
            head_lines=2,
            tail_lines=2,
            storage_dir=tmp_path,
        )
    )

    lines: list[str] = [f"Output row {i}" for i in range(1, 101)]
    lines[24] = "Output row 25: WARNING_TIMEOUT"
    lines[74] = "Output row 75: WARNING_TIMEOUT"
    raw_text = "\n".join(lines) + "\n"

    res = engine.prune_and_spill(raw_text, chat_id="chat-grep")
    assert res.metadata is not None

    grep_res: GrepRecallResult = engine.grep_evicted(res.metadata.spill_id, pattern=r"WARNING_TIMEOUT")
    assert grep_res.total_matches == 2
    assert len(grep_res.matches) == 2
    assert grep_res.matches[0].line_number == 25
    assert grep_res.matches[0].line_content == "Output row 25: WARNING_TIMEOUT"
    assert grep_res.matches[1].line_number == 75
    assert grep_res.matches[1].line_content == "Output row 75: WARNING_TIMEOUT"
