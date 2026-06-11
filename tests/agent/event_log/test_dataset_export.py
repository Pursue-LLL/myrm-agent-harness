"""Unit tests for dataset_export pipeline.

Tests quality filtering, format conversion (ShareGPT/Alpaca/OpenAI),
content deduplication, PII redaction integration, and the full
DatasetExporter pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.agent.event_log.dataset_export.exporter import DatasetExporter
from myrm_agent_harness.agent.event_log.dataset_export.format_converter import (
    content_hash,
    convert_trace,
    deduplicate,
)
from myrm_agent_harness.agent.event_log.dataset_export.protocols import (
    ExportConfig,
    ExportFormat,
    QualityThresholds,
)
from myrm_agent_harness.agent.event_log.dataset_export.quality_filter import passes_quality
from myrm_agent_harness.agent.event_log.trace_types import (
    ExecutionTrace,
    LLMCallRecord,
    ToolCallRecord,
    TraceMetadata,
    TraceOutcome,
)
from myrm_agent_harness.agent.event_log.types import EventFilter, EventPayload, StructuredEvent


# ---------------------------------------------------------------------------
# Test helpers
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
                events = [e for e in events if e.sequence >= event_filter.start_sequence]
            if event_filter.start_time is not None:
                events = [e for e in events if e.timestamp >= event_filter.start_time]
            if event_filter.end_time is not None:
                events = [e for e in events if e.timestamp <= event_filter.end_time]
            if event_filter.limit:
                events = events[: event_filter.limit]
        return events

    async def get_all_session_ids(self) -> list[str]:
        return sorted(self._events.keys())

    async def close(self) -> None:
        pass


def _make_trace(
    session_id: str = "test-session",
    outcome: TraceOutcome = TraceOutcome.SUCCESS,
    task_input: str = "Write a hello world function",
    output: str = "def hello(): return 'Hello, World!'",
    tool_calls: list[ToolCallRecord] | None = None,
    llm_calls: list[LLMCallRecord] | None = None,
) -> ExecutionTrace:
    """Create a test ExecutionTrace."""
    trace = ExecutionTrace(session_id=session_id)
    trace.outcome = outcome
    trace.task_input = task_input
    trace.output = output
    trace.start_time = 1700000000.0
    trace.end_time = 1700000010.0
    trace.duration_ms = 10000.0
    trace.total_tokens = 500
    trace.tool_calls = tool_calls or [
        ToolCallRecord(
            sequence=1,
            tool_name="code_runner",
            start_time=1700000001.0,
            end_time=1700000002.0,
            duration_ms=1000.0,
            success=True,
            input_data={"code": "print('hello')"},
            output_summary="Executed successfully",
        ),
    ]
    trace.llm_calls = llm_calls or [
        LLMCallRecord(
            sequence=2,
            start_time=1700000002.0,
            end_time=1700000005.0,
            model_name="gpt-4",
            duration_ms=3000.0,
            prompt_tokens=200,
            completion_tokens=300,
            total_tokens=500,
        ),
    ]
    return trace


def _make_session_events(
    session_id: str, task_input: str = "Test task", output: str = "Test output"
) -> list[StructuredEvent]:
    """Create minimal events that build_trace can aggregate into a valid trace."""
    return [
        StructuredEvent(
            sequence=1,
            timestamp=1700000000.0,
            event_type="session_start",
            session_id=session_id,
            data=EventPayload(**{"task_input": task_input, "_user_id": "u1"}),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=1700000001.0,
            event_type="tool_start",
            session_id=session_id,
            data=EventPayload(**{"tool_name": "code_runner", "code": "print('hi')"}),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=1700000002.0,
            event_type="tool_end",
            session_id=session_id,
            data=EventPayload(
                **{"tool_name": "code_runner", "output_summary": "ok", "duration_ms": 1000}
            ),
        ),
        StructuredEvent(
            sequence=4,
            timestamp=1700000003.0,
            event_type="llm_request",
            session_id=session_id,
            data=EventPayload(**{"model_name": "gpt-4", "message_count": 3}),
        ),
        StructuredEvent(
            sequence=5,
            timestamp=1700000005.0,
            event_type="token_usage",
            session_id=session_id,
            data=EventPayload(
                **{
                    "usage": {
                        "prompt_tokens": 200,
                        "completion_tokens": 100,
                        "total_tokens": 300,
                    },
                    "duration_ms": 2000,
                }
            ),
        ),
        StructuredEvent(
            sequence=6,
            timestamp=1700000010.0,
            event_type="session_end",
            session_id=session_id,
            data=EventPayload(**{"output": output, "summary": {"input_tokens": 200, "output_tokens": 100}}),
        ),
    ]


# ===========================================================================
# Quality filter tests
# ===========================================================================


class TestQualityFilter:
    def test_success_trace_passes(self) -> None:
        trace = _make_trace(outcome=TraceOutcome.SUCCESS)
        assert passes_quality(trace, QualityThresholds()) is True

    def test_failure_trace_rejected_when_require_success(self) -> None:
        trace = _make_trace(outcome=TraceOutcome.FAILURE)
        assert passes_quality(trace, QualityThresholds(require_success=True)) is False

    def test_failure_trace_passes_when_not_require_success(self) -> None:
        trace = _make_trace(outcome=TraceOutcome.FAILURE)
        assert passes_quality(trace, QualityThresholds(require_success=False)) is True

    def test_insufficient_turns_rejected(self) -> None:
        trace = ExecutionTrace(session_id="t")
        trace.outcome = TraceOutcome.SUCCESS
        trace.task_input = "a" * 30
        trace.output = "b" * 30
        trace.tool_calls = []
        trace.llm_calls = []
        assert passes_quality(trace, QualityThresholds(min_turns=2)) is False

    def test_sufficient_turns_passes(self) -> None:
        trace = _make_trace()
        assert passes_quality(trace, QualityThresholds(min_turns=2)) is True

    def test_short_content_rejected(self) -> None:
        trace = _make_trace(task_input="hi", output="ok")
        assert passes_quality(trace, QualityThresholds(min_content_length=50)) is False

    def test_long_content_passes(self) -> None:
        trace = _make_trace(task_input="a" * 30, output="b" * 30)
        assert passes_quality(trace, QualityThresholds(min_content_length=50)) is True


# ===========================================================================
# Format converter tests
# ===========================================================================


class TestFormatConverter:
    def test_sharegpt_format(self) -> None:
        trace = _make_trace()
        result = convert_trace(trace, ExportFormat.SHAREGPT)
        assert "conversations" in result
        conversations = result["conversations"]
        assert isinstance(conversations, list)
        assert len(conversations) >= 2
        assert conversations[0]["from"] == "human"
        assert conversations[-1]["from"] == "gpt"

    def test_alpaca_format(self) -> None:
        trace = _make_trace()
        result = convert_trace(trace, ExportFormat.ALPACA)
        assert "instruction" in result
        assert "input" in result
        assert "output" in result
        assert result["instruction"] == trace.task_input
        assert result["output"] == trace.output

    def test_openai_format(self) -> None:
        trace = _make_trace()
        result = convert_trace(trace, ExportFormat.OPENAI)
        assert "messages" in result
        messages = result["messages"]
        assert isinstance(messages, list)
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[-1]["role"] == "assistant"

    def test_openai_tool_calls(self) -> None:
        trace = _make_trace()
        result = convert_trace(trace, ExportFormat.OPENAI)
        messages = result["messages"]
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["name"] == "code_runner"

    def test_openai_arguments_is_valid_json(self) -> None:
        """Verify tool_calls.function.arguments is a valid JSON string, not Python repr."""
        trace = _make_trace()
        result = convert_trace(trace, ExportFormat.OPENAI)
        messages = result["messages"]
        assistant_tool_msgs = [
            m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_tool_msgs) >= 1
        for msg in assistant_tool_msgs:
            for tc in msg["tool_calls"]:
                args_str = tc["function"]["arguments"]
                assert isinstance(args_str, str)
                parsed = json.loads(args_str)
                assert isinstance(parsed, dict)

    def test_openai_empty_input_data_arguments(self) -> None:
        """Verify arguments is '{}' when tool has no input_data."""
        trace = _make_trace(
            tool_calls=[
                ToolCallRecord(
                    sequence=1,
                    tool_name="noop",
                    start_time=1700000001.0,
                    input_data={},
                    output_summary="done",
                ),
            ]
        )
        result = convert_trace(trace, ExportFormat.OPENAI)
        messages = result["messages"]
        assistant_tool_msgs = [
            m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_tool_msgs) == 1
        args_str = assistant_tool_msgs[0]["tool_calls"][0]["function"]["arguments"]
        assert args_str == "{}"

    def test_metadata_included(self) -> None:
        trace = _make_trace()
        for fmt in ExportFormat:
            result = convert_trace(trace, fmt)
            assert "metadata" in result
            meta = result["metadata"]
            assert meta["session_id"] == trace.session_id
            assert meta["outcome"] == "success"

    def test_content_hash_deterministic(self) -> None:
        sample = {"instruction": "test", "output": "result"}
        h1 = content_hash(sample)
        h2 = content_hash(sample)
        assert h1 == h2
        assert len(h1) == 64

    def test_deduplication(self) -> None:
        s1 = {"instruction": "a", "output": "b"}
        s2 = {"instruction": "a", "output": "b"}
        s3 = {"instruction": "c", "output": "d"}
        result = deduplicate([s1, s2, s3])
        assert len(result) == 2

    def test_empty_trace_formats(self) -> None:
        trace = _make_trace(task_input="", output="", tool_calls=[], llm_calls=[])
        trace.outcome = TraceOutcome.SUCCESS
        for fmt in ExportFormat:
            result = convert_trace(trace, fmt)
            assert isinstance(result, dict)


# ===========================================================================
# Full pipeline tests
# ===========================================================================


class TestDatasetExporter:
    @pytest.mark.asyncio
    async def test_export_basic(self, tmp_path: Path) -> None:
        backend = InMemoryBackend(
            {
                "s1": _make_session_events("s1", "Write a hello function", "def hello(): return 'Hello!'"),
                "s2": _make_session_events("s2", "Write a fizzbuzz function", "def fizzbuzz(): pass"),
            }
        )

        config = ExportConfig(
            output_dir=tmp_path / "exports",
            formats=(ExportFormat.SHAREGPT,),
            quality=QualityThresholds(require_success=True, min_turns=1, min_content_length=10),
            redact_pii=False,
        )

        exporter = DatasetExporter(backend)
        report = await exporter.export(config)

        assert report.total_sessions_scanned == 2
        assert report.traces_passed_quality == 2
        assert report.samples_exported >= 1
        assert len(report.output_files) == 1
        assert report.errors == []

        output_file = Path(report.output_files[0])
        assert output_file.exists()
        lines = output_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "conversations" in sample

    @pytest.mark.asyncio
    async def test_export_multiple_formats(self, tmp_path: Path) -> None:
        backend = InMemoryBackend(
            {"s1": _make_session_events("s1", "Test task with enough content for quality", "Output result with sufficient length")}
        )

        config = ExportConfig(
            output_dir=tmp_path / "exports",
            formats=(ExportFormat.SHAREGPT, ExportFormat.ALPACA, ExportFormat.OPENAI),
            quality=QualityThresholds(min_turns=1, min_content_length=10),
            redact_pii=False,
        )

        exporter = DatasetExporter(backend)
        report = await exporter.export(config)

        assert len(report.output_files) == 3

    @pytest.mark.asyncio
    async def test_export_empty_backend(self, tmp_path: Path) -> None:
        backend = InMemoryBackend()
        config = ExportConfig(output_dir=tmp_path / "exports", redact_pii=False)

        exporter = DatasetExporter(backend)
        report = await exporter.export(config)

        assert report.total_sessions_scanned == 0
        assert report.samples_exported == 0
        assert len(report.output_files) == 0

    @pytest.mark.asyncio
    async def test_max_samples_limit(self, tmp_path: Path) -> None:
        events = {
            f"s{i}": _make_session_events(f"s{i}", f"Task {i} content here long", f"Output {i} with enough length")
            for i in range(5)
        }
        backend = InMemoryBackend(events)

        config = ExportConfig(
            output_dir=tmp_path / "exports",
            max_samples=2,
            quality=QualityThresholds(min_turns=1, min_content_length=10),
            redact_pii=False,
        )

        exporter = DatasetExporter(backend)
        report = await exporter.export(config)

        assert report.traces_passed_quality <= 2

    @pytest.mark.asyncio
    async def test_incremental_export(self, tmp_path: Path) -> None:
        events = {
            "s1": _make_session_events("s1", "First task with enough content", "First output with enough length"),
        }
        backend = InMemoryBackend(events)

        state_file = tmp_path / "state.json"
        config = ExportConfig(
            output_dir=tmp_path / "exports",
            quality=QualityThresholds(min_turns=1, min_content_length=10),
            redact_pii=False,
            incremental_state_file=state_file,
        )

        exporter = DatasetExporter(backend)
        report1 = await exporter.export(config)
        assert report1.traces_passed_quality >= 1

        report2 = await exporter.export(config)
        assert report2.traces_passed_quality == 0

    @pytest.mark.asyncio
    async def test_type_error_on_invalid_backend(self) -> None:
        with pytest.raises(TypeError, match="Expected EventLogBackend"):
            DatasetExporter("not_a_backend")

    @pytest.mark.asyncio
    async def test_export_report_to_dict(self, tmp_path: Path) -> None:
        backend = InMemoryBackend(
            {"s1": _make_session_events("s1", "Task with enough content for quality", "Output with sufficient length")}
        )
        config = ExportConfig(
            output_dir=tmp_path / "exports",
            quality=QualityThresholds(min_turns=1, min_content_length=10),
            redact_pii=False,
        )

        exporter = DatasetExporter(backend)
        report = await exporter.export(config)
        d = report.to_dict()

        assert isinstance(d, dict)
        assert "total_sessions_scanned" in d
        assert "duration_ms" in d
        assert isinstance(d["duration_ms"], float)
