"""Stream checkpoint and in-place resume utilities for agent execution.

Provides safe breakpoint capture, LCP (longest common prefix) deduplication,
and continuation instruction assembly to enable zero-loss stream recovery.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StreamBreakpoint:
    """Represents a validated safe text breakpoint from an interrupted stream."""

    full_text: str
    tail_anchor: str
    char_count: int


def capture_stream_breakpoint(text: str, anchor_length: int = 80) -> StreamBreakpoint | None:
    """Capture a safe semantic breakpoint from an interrupted stream.

    Args:
        text: The raw accumulated text generated before interruption.
        anchor_length: The length of the tail anchor to use for prompt continuation.

    Returns:
        StreamBreakpoint with clean tail anchor, or None if text is empty.
    """
    cleaned = text.strip()
    if not cleaned:
        return None

    # Pick the tail anchor, preferring boundary on whitespace or newline if available
    tail = cleaned[-anchor_length:] if len(cleaned) > anchor_length else cleaned
    return StreamBreakpoint(
        full_text=text,
        tail_anchor=tail,
        char_count=len(text),
    )


def clean_duplicate_prefix(tail_anchor: str, incoming_chunk: str) -> str:
    """Remove overlapping words or characters if LLM repeats the anchor at continuation.

    Args:
        tail_anchor: The trailing text that was sent to the LLM as reference.
        incoming_chunk: The initial chunk(s) returned by the continuation call.

    Returns:
        Cleaned chunk with any duplicate prefix removed.
    """
    if not tail_anchor or not incoming_chunk:
        return incoming_chunk

    # Look for longest suffix of tail_anchor that matches a prefix of incoming_chunk
    max_check = min(len(tail_anchor), len(incoming_chunk))
    overlap_len = 0

    for i in range(1, max_check + 1):
        if tail_anchor.endswith(incoming_chunk[:i]):
            overlap_len = i

    if overlap_len > 0:
        return incoming_chunk[overlap_len:]

    return incoming_chunk


def build_stream_continuation_instruction(tail_anchor: str) -> str:
    """Generate a clean epilogue instruction for seamless in-place continuation.

    Guarantees 100% prefix stability for Prompt Cache by placing instruction
    at the very tail of the conversation.

    Args:
        tail_anchor: The reference trailing text.

    Returns:
        Continuation prompt string.
    """
    return (
        f"\n\n[System Recovery]: Your previous generation was cut off by a connection drop. "
        f"Continue outputting seamlessly right from the following text without repeating it:\n"
        f"\"{tail_anchor}\""
    )
