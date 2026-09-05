"""Unit tests for stream resume checkpoint and LCP deduplication."""

import pytest
from myrm_agent_harness.agent.streaming import (
    StreamBreakpoint,
    build_stream_continuation_instruction,
    capture_stream_breakpoint,
    clean_duplicate_prefix,
)


def test_capture_stream_breakpoint_success() -> None:
    text = "function calculateTotal(price: number, tax: number): number {\n    return price * (1 + tax);\n}"
    bp = capture_stream_breakpoint(text, anchor_length=30)
    assert bp is not None
    assert isinstance(bp, StreamBreakpoint)
    assert bp.full_text == text
    assert len(bp.tail_anchor) <= 30
    assert bp.tail_anchor.endswith(";\n}")


def test_capture_stream_breakpoint_empty() -> None:
    assert capture_stream_breakpoint("") is None
    assert capture_stream_breakpoint("   \n\t  ") is None


def test_clean_duplicate_prefix_exact_overlap() -> None:
    tail_anchor = "return price * (1 + tax);"
    incoming_chunk = "(1 + tax); console.log('done');"
    cleaned = clean_duplicate_prefix(tail_anchor, incoming_chunk)
    assert cleaned == " console.log('done');"


def test_clean_duplicate_prefix_no_overlap() -> None:
    tail_anchor = "function test() {"
    incoming_chunk = "\n    const a = 1;"
    cleaned = clean_duplicate_prefix(tail_anchor, incoming_chunk)
    assert cleaned == incoming_chunk


def test_clean_duplicate_prefix_empty_inputs() -> None:
    assert clean_duplicate_prefix("", "chunk") == "chunk"
    assert clean_duplicate_prefix("anchor", "") == ""


def test_build_stream_continuation_instruction() -> None:
    tail = "const result = await fetch();"
    instruction = build_stream_continuation_instruction(tail)
    assert tail in instruction
    assert "System Recovery" in instruction
    assert instruction.startswith("\n\n")
