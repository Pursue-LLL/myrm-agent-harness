"""Unit tests for DoubleLayerErrorPreserver and ResilientStreamReplayer.

Tests benchmarked against IHUI-AI commit 6ce28c444 streamChat error chain preservation invariants:
1. Error classification and dual-layer preservation without loss of root cause.
2. Normal streaming without glitches.
3. Mid-stream transient glitch auto-recovery from last_acked_seq cursor.
4. Immediate failure propagation on fatal error and retry budget exhaustion.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from myrm_agent_harness.runtime.stream_resilience import (
    DoubleLayerErrorPreserver,
    NestedStreamError,
    ResilientStreamReplayer,
    StreamChunkEvent,
    StreamErrorKind,
)


def test_double_layer_error_preserver_transient_vs_fatal() -> None:
    """Test classification of transient versus non-retriable exceptions and markdown formatting."""
    # 1. Transient socket reset
    raw_socket_err = ConnectionResetError("Connection reset by peer")
    wrapped_socket = DoubleLayerErrorPreserver.wrap_exception(raw_socket_err, last_acked_seq=5)
    assert wrapped_socket.error_kind == StreamErrorKind.TRANSPORT_RESET
    assert wrapped_socket.is_retriable is True
    assert wrapped_socket.last_acked_seq == 5
    assert "ConnectionResetError" in wrapped_socket.cause_error_name

    md_socket = DoubleLayerErrorPreserver.render_diagnostic_markdown(wrapped_socket)
    assert "### 🚨 流式通信双层异常链路诊断卡片" in md_socket
    assert "✅ 允许重试" in md_socket
    assert "> [!NOTE]" in md_socket

    # 2. Corrupted JSON chunk
    raw_json_err = json.JSONDecodeError("Unterminated string starting at line 1", "{\"msg\": \"foo", 12)
    wrapped_json = DoubleLayerErrorPreserver.wrap_exception(
        raw_json_err, raw_chunk="{\"msg\": \"foo", last_acked_seq=8
    )
    assert wrapped_json.error_kind == StreamErrorKind.MALFORMED_CHUNK
    assert wrapped_json.is_retriable is True
    assert wrapped_json.last_acked_seq == 8

    # 3. Non-retriable fatal authentication / protocol error
    fatal_err = PermissionError("HTTP 401 Unauthorized token expired")
    wrapped_fatal = DoubleLayerErrorPreserver.wrap_exception(fatal_err, last_acked_seq=2)
    assert wrapped_fatal.is_retriable is False
    md_fatal = DoubleLayerErrorPreserver.render_diagnostic_markdown(wrapped_fatal)
    assert "❌ 不可重试 (终止)" in md_fatal
    assert "> [!CAUTION]" in md_fatal


def test_resilient_stream_replayer_happy_path() -> None:
    """Test undisturbed stream consumption yielding all sequential events."""
    replayer = ResilientStreamReplayer(max_retries=2)

    def factory(from_seq: int) -> Iterator[StreamChunkEvent]:
        chunks = [
            StreamChunkEvent(seq_id=0, event_type="token", content="Hello"),
            StreamChunkEvent(seq_id=1, event_type="token", content=" "),
            StreamChunkEvent(seq_id=2, event_type="token", content="World", is_final=True),
        ]
        for c in chunks:
            if c.seq_id > from_seq:
                yield c

    received = list(replayer.consume_stream_with_resilience("sess_ok", factory))
    assert len(received) == 3
    assert "".join(c.content for c in received) == "Hello World"


def test_resilient_stream_replayer_auto_recovery_from_glitch() -> None:
    """Test seamless mid-stream recovery from last_acked_seq when transient connection drops."""
    replayer = ResilientStreamReplayer(
        max_retries=2,
        initial_backoff_seconds=0.01,
        backoff_factor=1.5,
    )

    attempt_counter = 0

    def unreliable_factory(from_seq: int) -> Iterator[StreamChunkEvent]:
        nonlocal attempt_counter
        attempt_counter += 1

        all_events = [
            StreamChunkEvent(seq_id=0, event_type="token", content="Step 1: "),
            StreamChunkEvent(seq_id=1, event_type="token", content="Plan; "),
            StreamChunkEvent(seq_id=2, event_type="token", content="Step 2: "),
            StreamChunkEvent(seq_id=3, event_type="token", content="Execute; "),
            StreamChunkEvent(seq_id=4, event_type="token", content="Done.", is_final=True),
        ]

        for ev in all_events:
            if ev.seq_id <= from_seq:
                continue

            # Simulate network interruption after yielding seq_id=2 on first attempt
            if attempt_counter == 1 and ev.seq_id == 3:
                raise ConnectionResetError("Mid-stream connection reset by peer")

            yield ev

    received = list(replayer.consume_stream_with_resilience("sess_unreliable", unreliable_factory))

    # All 5 events must be seamlessly received in strict monotonic order
    assert len(received) == 5
    assert [c.seq_id for c in received] == [0, 1, 2, 3, 4]
    assert "".join(c.content for c in received) == "Step 1: Plan; Step 2: Execute; Done."
    assert attempt_counter == 2  # Reconnected exactly once


def test_resilient_stream_replayer_fatal_and_budget_exhaustion() -> None:
    """Test fatal error stops immediately and retriable error raises NestedStreamException on exhaustion."""
    replayer = ResilientStreamReplayer(
        max_retries=2,
        initial_backoff_seconds=0.01,
    )

    # Case A: Fatal non-retriable error
    def fatal_factory(from_seq: int) -> Iterator[StreamChunkEvent]:
        yield StreamChunkEvent(seq_id=0, event_type="token", content="Start")
        raise PermissionError("403 Forbidden")

    with pytest.raises(NestedStreamError) as exc_info:
        list(replayer.consume_stream_with_resilience("sess_fatal", fatal_factory))

    assert exc_info.value.is_retriable is False
    assert "PermissionError" in exc_info.value.cause_error_name

    # Case B: Exhaustion of retriable attempts
    def continuous_failure_factory(from_seq: int) -> Iterator[StreamChunkEvent]:
        raise ConnectionResetError("Network persistently down")

    with pytest.raises(NestedStreamError) as exc_exhausted:
        list(replayer.consume_stream_with_resilience("sess_exhaust", continuous_failure_factory))

    assert exc_exhausted.value.is_retriable is True
    assert exc_exhausted.value.error_kind == StreamErrorKind.TRANSPORT_RESET
    assert "ConnectionResetError" in exc_exhausted.value.cause_error_name
