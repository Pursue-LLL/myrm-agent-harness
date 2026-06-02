"""Unit tests for trace_types and trace_builder.

Tests ExecutionTrace aggregation from raw events, metadata extraction,
dimension filtering, and incremental builds.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.event_log.trace_builder import build_trace, query_traces
from myrm_agent_harness.agent.event_log.trace_types import (
    ExecutionTrace,
    ToolCallRecord,
    TraceMetadata,
    TraceOutcome,
)
from myrm_agent_harness.agent.event_log.types import EventFilter, StructuredEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class InMemoryBackend:
    """Minimal in-memory backend for testing."""

    def __init__(self, events: dict[str, list[StructuredEvent]] | None = None) -> None:
        self._events: dict[str, list[StructuredEvent]] = events or {}

    async def append(self, events: list[StructuredEvent]) -> None:
        for e in events:
            self._events.setdefault(e.session_id, []).append(e)

    async def get_events(
        self, session_id: str, event_filter: EventFilter | None = None
    ) -> list[StructuredEvent]:
        events = self._events.get(session_id, [])
        if event_filter:
            if event_filter.start_sequence is not None:
                events = [
                    e for e in events if e.sequence >= event_filter.start_sequence
                ]
            if event_filter.start_time is not None:
                events = [e for e in events if e.timestamp >= event_filter.start_time]
            if event_filter.end_time is not None:
                events = [e for e in events if e.timestamp <= event_filter.end_time]
            if event_filter.event_types:
                events = [e for e in events if e.event_type in event_filter.event_types]
            if event_filter.limit:
                events = events[: event_filter.limit]
        return events

    async def get_all_session_ids(self) -> list[str]:
        return sorted(self._events.keys())

    async def close(self) -> None:
        pass


def _event(
    seq: int,
    event_type: str,
    session_id: str = "sess-1",
    ts: float = 1700000000.0,
    **data: object,
) -> StructuredEvent:
    return StructuredEvent(
        sequence=seq,
        timestamp=ts + seq,
        event_type=event_type,
        session_id=session_id,
        data=dict(data),
    )


# ---------------------------------------------------------------------------
# TraceMetadata
# ---------------------------------------------------------------------------


class TestTraceMetadata:
    def test_defaults(self) -> None:
        meta = TraceMetadata()
        assert meta.user_id is None
        assert meta.agent_id is None
        assert meta.task_type is None
        assert meta.trace_id is None

    def test_frozen(self) -> None:
        meta = TraceMetadata(user_id="u1")
        with pytest.raises(AttributeError):
            meta.user_id = "u2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ToolCallRecord
# ---------------------------------------------------------------------------


class TestToolCallRecord:
    def test_frozen(self) -> None:
        record = ToolCallRecord(sequence=1, tool_name="bash", start_time=0.0)
        with pytest.raises(AttributeError):
            record.tool_name = "file_read"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ExecutionTrace
# ---------------------------------------------------------------------------


class TestExecutionTrace:
    def test_to_dict(self) -> None:
        trace = ExecutionTrace(
            session_id="s1",
            metadata=TraceMetadata(user_id="u1", trace_id="abc123"),
            outcome=TraceOutcome.SUCCESS,
            start_time=100.0,
            end_time=110.0,
            duration_ms=10000.0,
            task_input="do something",
            output="done",
        )
        d = trace.to_dict()
        assert d["session_id"] == "s1"
        assert d["metadata"]["user_id"] == "u1"
        assert d["outcome"] == "success"
        assert d["duration_ms"] == 10000.0


# ---------------------------------------------------------------------------
# build_trace
# ---------------------------------------------------------------------------


class TestBuildTrace:
    @pytest.mark.asyncio
    async def test_basic_successful_trace(self) -> None:
        events = [
            _event(1, "session_start", _user_id="user-1", _agent_id="agent-1"),
            _event(2, "tool_start", tool_name="file_read"),
            _event(3, "tool_end", tool_name="file_read", duration_ms=100.0),
            _event(4, "tool_start", tool_name="bash"),
            _event(5, "tool_end", tool_name="bash", duration_ms=500.0),
            _event(
                6, "session_end", summary={"input_tokens": 100, "output_tokens": 50}
            ),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.session_id == "sess-1"
        assert trace.metadata.user_id == "user-1"
        assert trace.metadata.agent_id == "agent-1"
        assert trace.outcome == TraceOutcome.SUCCESS
        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].tool_name == "file_read"
        assert trace.tool_calls[0].success is True
        assert trace.tool_calls[0].duration_ms == 100.0
        assert trace.tool_calls[1].tool_name == "bash"
        assert trace.total_events == 6
        assert trace.total_tokens == 150

    @pytest.mark.asyncio
    async def test_failed_trace(self) -> None:
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="bash"),
            _event(
                3,
                "tool_failure",
                tool_name="bash",
                error="command failed",
                duration_ms=200.0,
            ),
            _event(4, "error", error="task failed", error_type="RuntimeError"),
            _event(5, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.outcome == TraceOutcome.FAILURE
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].success is False
        assert trace.tool_calls[0].error == "command failed"
        assert len(trace.errors) == 1
        assert trace.errors[0]["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_human_feedback(self) -> None:
        events = [
            _event(1, "session_start"),
            _event(
                2,
                "tool_approval_request",
                tool_name="bash",
                action="run rm -rf /",
                approved=False,
            ),
            _event(3, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.human_feedback) == 1
        assert trace.human_feedback[0]["tool_name"] == "bash"
        assert trace.human_feedback[0]["approved"] is False

    @pytest.mark.asyncio
    async def test_empty_session(self) -> None:
        backend = InMemoryBackend({})
        trace = await build_trace(backend, "nonexistent")

        assert trace.session_id == "nonexistent"
        assert trace.outcome == TraceOutcome.UNKNOWN
        assert trace.total_events == 0

    @pytest.mark.asyncio
    async def test_incremental_build(self) -> None:
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="bash"),
            _event(3, "tool_end", tool_name="bash", duration_ms=100.0),
            _event(4, "tool_start", tool_name="file_read"),
            _event(5, "tool_end", tool_name="file_read", duration_ms=50.0),
        ]
        backend = InMemoryBackend({"sess-1": events})

        trace = await build_trace(backend, "sess-1", start_sequence=4)
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "file_read"


# ---------------------------------------------------------------------------
# query_traces
# ---------------------------------------------------------------------------


class TestQueryTraces:
    @pytest.mark.asyncio
    async def test_filter_by_user_id(self) -> None:
        backend = InMemoryBackend(
            {
                "sess-1": [
                    _event(1, "session_start", session_id="sess-1", _user_id="user-a"),
                    _event(2, "session_end", session_id="sess-1"),
                ],
                "sess-2": [
                    _event(1, "session_start", session_id="sess-2", _user_id="user-b"),
                    _event(2, "session_end", session_id="sess-2"),
                ],
            }
        )

        traces = await query_traces(backend, user_id="user-a")
        assert len(traces) == 1
        assert traces[0].session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_limit(self) -> None:
        backend = InMemoryBackend(
            {
                f"sess-{i}": [
                    _event(1, "session_start", session_id=f"sess-{i}"),
                    _event(2, "session_end", session_id=f"sess-{i}"),
                ]
                for i in range(5)
            }
        )

        traces = await query_traces(backend, limit=2)
        assert len(traces) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_tool_failure_without_preceding_tool_start(self) -> None:
        """tool_failure without a matching tool_start should still produce a record."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_failure", tool_name="bash", error="unexpected failure"),
            _event(3, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].success is False
        assert trace.tool_calls[0].error == "unexpected failure"
        assert trace.tool_calls[0].input_data == {}

    @pytest.mark.asyncio
    async def test_tool_start_without_tool_end(self) -> None:
        """tool_start without a corresponding tool_end — pending tool is never completed."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="long_running"),
            _event(3, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_missing_event_data_fields(self) -> None:
        """Events with missing expected data fields should not crash."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start"),
            _event(3, "tool_end"),
            _event(4, "error"),
            _event(5, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.total_events == 5
        assert len(trace.tool_calls) == 0
        assert len(trace.errors) == 1

    @pytest.mark.asyncio
    async def test_multiple_errors(self) -> None:
        """Multiple error events should all be captured."""
        events = [
            _event(1, "session_start"),
            _event(2, "error", error="first error", error_type="ValueError"),
            _event(3, "error", error="second error", error_type="IOError"),
            _event(4, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.outcome == TraceOutcome.FAILURE
        assert len(trace.errors) == 2

    @pytest.mark.asyncio
    async def test_task_input_extraction_variants(self) -> None:
        """session_start should try task_input, query, and message fields."""
        for key in ("task_input", "query", "message"):
            events = [
                _event(1, "session_start", **{key: "hello world"}),
                _event(2, "session_end"),
            ]
            backend = InMemoryBackend({"sess-1": events})
            trace = await build_trace(backend, "sess-1")
            assert trace.task_input == "hello world", f"Failed for key={key}"

    @pytest.mark.asyncio
    async def test_output_extraction_variants(self) -> None:
        """session_end should try output and result fields."""
        for key in ("output", "result"):
            events = [
                _event(1, "session_start"),
                _event(2, "session_end", **{key: "completed"}),
            ]
            backend = InMemoryBackend({"sess-1": events})
            trace = await build_trace(backend, "sess-1")
            assert trace.output == "completed", f"Failed for key={key}"

    @pytest.mark.asyncio
    async def test_unknown_event_types_ignored(self) -> None:
        """Unknown event types should be silently ignored."""
        events = [
            _event(1, "session_start"),
            _event(2, "custom_metric", value=42),
            _event(3, "internal_debug", msg="test"),
            _event(4, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.total_events == 4
        assert len(trace.tool_calls) == 0
        assert len(trace.errors) == 0

    @pytest.mark.asyncio
    async def test_session_without_session_start(self) -> None:
        """Events without session_start — start_time remains 0."""
        events = [
            _event(1, "tool_start", tool_name="bash"),
            _event(2, "tool_end", tool_name="bash"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.start_time == 0.0
        assert trace.total_events == 2

    @pytest.mark.asyncio
    async def test_session_without_session_end(self) -> None:
        """Events without session_end — outcome remains UNKNOWN."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="bash"),
            _event(3, "tool_end", tool_name="bash"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.outcome == TraceOutcome.UNKNOWN
        assert trace.end_time == 0.0

    @pytest.mark.asyncio
    async def test_to_dict_with_tool_calls(self) -> None:
        """to_dict should serialize tool_calls correctly."""
        trace = ExecutionTrace(session_id="s1")
        trace.tool_calls = [
            ToolCallRecord(
                sequence=1,
                tool_name="bash",
                start_time=100.0,
                end_time=101.0,
                duration_ms=1000.0,
                success=True,
            ),
            ToolCallRecord(
                sequence=2,
                tool_name="file_read",
                start_time=101.0,
                end_time=102.0,
                success=False,
                error="not found",
            ),
        ]
        d = trace.to_dict()
        assert len(d["tool_calls"]) == 2
        assert d["tool_calls"][0]["tool_name"] == "bash"
        assert d["tool_calls"][1]["success"] is False

    @pytest.mark.asyncio
    async def test_query_traces_filter_by_task_type(self) -> None:
        """query_traces should filter by task_type."""
        backend = InMemoryBackend(
            {
                "sess-1": [
                    _event(
                        1, "session_start", session_id="sess-1", _task_type="coding"
                    ),
                    _event(2, "session_end", session_id="sess-1"),
                ],
                "sess-2": [
                    _event(
                        1, "session_start", session_id="sess-2", _task_type="search"
                    ),
                    _event(2, "session_end", session_id="sess-2"),
                ],
            }
        )

        traces = await query_traces(backend, task_type="coding")
        assert len(traces) == 1
        assert traces[0].metadata.task_type == "coding"

    @pytest.mark.asyncio
    async def test_concurrent_same_tool_calls(self) -> None:
        """Two parallel calls to the same tool should both produce records (FIFO matching)."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="bash"),
            _event(3, "tool_start", tool_name="bash"),
            _event(4, "tool_end", tool_name="bash", duration_ms=100.0),
            _event(5, "tool_end", tool_name="bash", duration_ms=200.0),
            _event(6, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].sequence == 2
        assert trace.tool_calls[0].duration_ms == 100.0
        assert trace.tool_calls[1].sequence == 3
        assert trace.tool_calls[1].duration_ms == 200.0

    @pytest.mark.asyncio
    async def test_tool_end_without_matching_tool_start(self) -> None:
        """tool_end with no matching pending tool_start should be silently ignored."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_end", tool_name="file_read", duration_ms=50.0),
            _event(3, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_non_string_task_input_ignored(self) -> None:
        """Non-string task_input (e.g. dict/int) should be ignored."""
        events = [
            _event(1, "session_start", task_input={"complex": True}),
            _event(2, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.task_input == ""

    @pytest.mark.asyncio
    async def test_summary_non_dict_ignored(self) -> None:
        """Non-dict summary in session_end should not crash."""
        events = [
            _event(1, "session_start"),
            _event(2, "session_end", summary="just a string"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.total_tokens == 0

    @pytest.mark.asyncio
    async def test_negative_duration_when_end_before_start(self) -> None:
        """duration_ms should be negative if end_time < start_time (clock drift)."""
        events = [
            _event(1, "session_start", ts=1700000010.0),
            _event(2, "session_end", ts=1700000000.0),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.start_time == 1700000011.0
        assert trace.end_time == 1700000002.0
        assert trace.duration_ms < 0

    @pytest.mark.asyncio
    async def test_tool_end_missing_tool_name(self) -> None:
        """tool_end without tool_name field should be silently ignored."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="bash"),
            _event(3, "tool_end", duration_ms=50.0),
            _event(4, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_query_traces_skips_empty_sessions(self) -> None:
        """Sessions with no events should be skipped in query_traces."""
        backend = InMemoryBackend(
            {
                "sess-1": [],
                "sess-2": [
                    _event(1, "session_start", session_id="sess-2"),
                    _event(2, "session_end", session_id="sess-2"),
                ],
            }
        )

        traces = await query_traces(backend)
        assert len(traces) == 1
        assert traces[0].session_id == "sess-2"

    @pytest.mark.asyncio
    async def test_query_traces_time_range_filter(self) -> None:
        """query_traces should pass start_time/end_time to backend filter."""
        backend = InMemoryBackend(
            {
                "sess-1": [
                    _event(1, "session_start", session_id="sess-1", ts=1700000000.0),
                    _event(2, "session_end", session_id="sess-1", ts=1700000010.0),
                ],
                "sess-2": [
                    _event(1, "session_start", session_id="sess-2", ts=1700001000.0),
                    _event(2, "session_end", session_id="sess-2", ts=1700001010.0),
                ],
            }
        )

        traces = await query_traces(backend, start_time=1700000500.0)
        assert len(traces) == 1
        assert traces[0].session_id == "sess-2"

    @pytest.mark.asyncio
    async def test_tool_failure_missing_tool_name(self) -> None:
        """tool_failure without tool_name should be silently ignored."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_failure", error="some error"),
            _event(3, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_non_string_output_ignored(self) -> None:
        """Non-string output (e.g. dict) in session_end should be ignored."""
        events = [
            _event(1, "session_start"),
            _event(2, "session_end", output={"structured": True}),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert trace.output == ""

    @pytest.mark.asyncio
    async def test_tool_failure_empty_error_yields_none(self) -> None:
        """tool_failure with empty error string should set error=None."""
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="bash"),
            _event(3, "tool_failure", tool_name="bash", error=""),
            _event(4, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error is None

    @pytest.mark.asyncio
    async def test_tool_end_captures_output_data(self) -> None:
        events = [
            _event(1, "session_start"),
            _event(2, "tool_start", tool_name="bash", command="echo hi"),
            _event(
                3,
                "tool_end",
                tool_name="bash",
                duration_ms=50.0,
                output="hi\n",
                output_summary="hi",
            ),
            _event(4, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].input_data == {"command": "echo hi"}
        assert trace.tool_calls[0].output_data == "hi\n"
        assert trace.tool_calls[0].output_summary == "hi"

        d = trace.to_dict()
        assert d["tool_calls"][0]["input_data"] == {"command": "echo hi"}
        assert d["tool_calls"][0]["output_data"] == "hi\n"

    @pytest.mark.asyncio
    async def test_token_usage_legacy_end_time_fallback(self) -> None:
        ts = 1700000005.0
        events = [
            _event(1, "session_start"),
            _event(
                2,
                "token_usage",
                ts=ts,
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
                model_name="gpt-4o",
            ),
            _event(3, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.llm_calls) == 1
        assert trace.llm_calls[0].end_time == ts + 2
        assert trace.llm_calls[0].start_time == ts + 2
        assert trace.llm_calls[0].model_name == "gpt-4o"
        assert trace.llm_calls[0].total_tokens == 150

    @pytest.mark.asyncio
    async def test_llm_request_merged_with_token_usage(self) -> None:
        ts = 1700000000.0
        events = [
            _event(1, "session_start"),
            _event(
                2,
                "llm_request",
                ts=ts,
                model_name="gpt-4o",
                prompt_preview="[user] hello",
                message_count=3,
            ),
            _event(
                3,
                "token_usage",
                ts=ts,
                duration_ms=2000.0,
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                model_name="gpt-4o",
            ),
            _event(4, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.llm_calls) == 1
        lc = trace.llm_calls[0]
        assert lc.sequence == 2
        assert lc.start_time == ts + 2
        assert lc.end_time == ts + 3
        assert lc.prompt_preview == "[user] hello"
        assert lc.message_count == 3
        assert lc.duration_ms == 2000.0

    @pytest.mark.asyncio
    async def test_token_usage_legacy_duration_backcalculates_start(self) -> None:
        ts = 1700000005.0
        events = [
            _event(1, "session_start"),
            _event(
                2,
                "token_usage",
                ts=ts,
                duration_ms=3000.0,
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                model_name="gpt-4o",
            ),
            _event(3, "session_end"),
        ]
        backend = InMemoryBackend({"sess-1": events})
        trace = await build_trace(backend, "sess-1")

        assert len(trace.llm_calls) == 1
        lc = trace.llm_calls[0]
        assert lc.end_time == ts + 2
        assert lc.start_time == lc.end_time - 3.0
        assert lc.duration_ms == 3000.0
