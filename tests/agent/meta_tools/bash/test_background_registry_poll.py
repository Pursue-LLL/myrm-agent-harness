"""Tests for background registry poll snapshot builder."""

from collections import deque

from myrm_agent_harness.agent.meta_tools.bash._background.poll import build_poll_output


def test_build_poll_output_incremental_slice() -> None:
    stdout = deque([(1, "a"), (2, "b"), (3, "c")])
    stderr: deque[tuple[int, str]] = deque()
    payload, streak = build_poll_output(
        stdout_buffer=stdout,
        stderr_buffer=stderr,
        cursor=3,
        empty_poll_streak=0,
        max_lines=10,
        since_cursor=1,
    )
    assert payload["stdout"] == ["b", "c"]
    assert payload["next_cursor"] == 3
    assert streak == 0


def test_build_poll_output_marks_dropped_when_ring_evicts() -> None:
    stdout = deque([(100, f"out-{i}") for i in range(200)], maxlen=200)
    stderr = deque([(100, f"err-{i}") for i in range(200)], maxlen=200)
    payload, streak = build_poll_output(
        stdout_buffer=stdout,
        stderr_buffer=stderr,
        cursor=200,
        empty_poll_streak=2,
        max_lines=10,
        since_cursor=50,
    )
    assert payload["dropped"] is True
    assert streak == 0


def test_build_poll_output_forward_slice_advances_cursor_accurately() -> None:
    # 5 items (cursors 10..14), request max_lines=2 with since_cursor=9
    stdout = deque([(10, "line-10"), (11, "line-11"), (12, "line-12"), (13, "line-13"), (14, "line-14")])
    stderr: deque[tuple[int, str]] = deque()
    payload, streak = build_poll_output(
        stdout_buffer=stdout,
        stderr_buffer=stderr,
        cursor=14,
        empty_poll_streak=0,
        max_lines=2,
        since_cursor=9,
    )
    # Should yield forward first 2 lines (10, 11) and advance next_cursor to 11
    assert payload["stdout"] == ["line-10", "line-11"]
    assert payload["next_cursor"] == 11

