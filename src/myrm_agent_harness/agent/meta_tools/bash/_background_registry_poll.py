"""Incremental poll snapshot builder for background bash stdout/stderr rings.

[INPUT]
- collections.deque ring buffers of (cursor, text) pairs

[OUTPUT]
- build_poll_output: stdout/stderr slices + next_cursor + poll_hint

[POS]
Extracted from BackgroundProcessRegistry.get_output for file-size and test isolation.
"""

from __future__ import annotations

from collections import deque

_OUTPUT_TAIL_LINES = 200
_POLL_BACKOFF_MS: tuple[int, ...] = (5000, 10000, 20000, 30000, 60000)


def build_poll_output(
    *,
    stdout_buffer: deque[tuple[int, str]],
    stderr_buffer: deque[tuple[int, str]],
    cursor: int,
    empty_poll_streak: int,
    max_lines: int,
    since_cursor: int | None,
) -> tuple[dict[str, object], int]:
    """Return poll payload and updated empty_poll_streak."""
    baseline = since_cursor if since_cursor is not None else 0
    next_cursor = cursor
    stdout_filtered = [text for cur, text in stdout_buffer if cur > baseline]
    stderr_filtered = [text for cur, text in stderr_buffer if cur > baseline]
    has_new_output = bool(stdout_filtered or stderr_filtered)
    streak = empty_poll_streak
    if since_cursor is not None:
        streak = 0 if has_new_output else empty_poll_streak + 1
    streak_idx = min(streak, len(_POLL_BACKOFF_MS) - 1)
    poll_hint = {
        "has_new_output": has_new_output,
        "suggested_wait_ms": _POLL_BACKOFF_MS[streak_idx],
    }

    if since_cursor is not None and stdout_buffer and stderr_buffer:
        oldest_kept = min(
            stdout_buffer[0][0] if stdout_buffer else next_cursor,
            stderr_buffer[0][0] if stderr_buffer else next_cursor,
        )
        dropped = oldest_kept > baseline + 1 and (
            len(stdout_buffer) == _OUTPUT_TAIL_LINES or len(stderr_buffer) == _OUTPUT_TAIL_LINES
        )
    else:
        dropped = False

    payload: dict[str, object] = {
        "stdout": stdout_filtered[-max_lines:],
        "stderr": stderr_filtered[-max_lines:],
        "next_cursor": next_cursor,
        "dropped": dropped,
        "poll_hint": poll_hint,
    }
    return payload, streak


__all__ = ["build_poll_output"]
