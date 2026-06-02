"""Pipeline 异常隔离 + Summarize 断路器测试"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import BaseProcessor, ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.engine import ContextPipeline
from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
    MAX_CONSECUTIVE_SUMMARIZE_FAILURES,
    SummarizeProcessor,
    _build_deterministic_summary,
    _classify_error_type,
    _get_failures,
    _set_failures,
)


def _make_context(**overrides) -> ProcessorContext:
    defaults = {
        "messages": [HumanMessage(content="hello")],
        "user_query": "test",
    }
    defaults.update(overrides)
    return ProcessorContext(**defaults)


class _AlwaysProcessor(BaseProcessor):
    """Always executes, appends its name to operations."""

    def __init__(self, tag: str = "always"):
        self._tag = tag

    @property
    def name(self) -> str:
        return self._tag

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        context.tokens_saved += 10
        return context


class _FailingProcessor(BaseProcessor):
    """Always raises in process()."""

    @property
    def name(self) -> str:
        return "failing"

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        raise RuntimeError("boom")


class _SkipProcessor(BaseProcessor):
    """Always skips."""

    @property
    def name(self) -> str:
        return "skip"

    async def should_process(self, context: ProcessorContext) -> bool:
        return False

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        return context


# ─────────────────────────────────────────────────────────────
# Pipeline 异常隔离
# ─────────────────────────────────────────────────────────────


class TestPipelineErrorIsolation:
    @pytest.mark.asyncio
    async def test_failing_processor_does_not_block_subsequent(self):
        pipeline = ContextPipeline(
            [
                _AlwaysProcessor("pre"),
                _FailingProcessor(),
                _AlwaysProcessor("post"),
            ]
        )
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert "pre" in result.operations
        assert "post" in result.operations
        assert "failing" not in result.operations
        assert result.tokens_saved == 20

    @pytest.mark.asyncio
    async def test_all_processors_fail_returns_original_context(self):
        pipeline = ContextPipeline([_FailingProcessor()])
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert result.operations == []
        assert result.tokens_saved == 0

    @pytest.mark.asyncio
    async def test_no_failure_normal_execution(self):
        pipeline = ContextPipeline(
            [
                _AlwaysProcessor("a"),
                _SkipProcessor(),
                _AlwaysProcessor("b"),
            ]
        )
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert result.operations == ["a", "b"]
        assert result.tokens_saved == 20

    @pytest.mark.asyncio
    async def test_context_preserved_after_failure(self):
        """After a failure, context from the previous successful processor is used."""
        pipeline = ContextPipeline(
            [
                _AlwaysProcessor("pre"),
                _FailingProcessor(),
            ]
        )
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert result.tokens_saved == 10
        assert result.operations == ["pre"]


# ─────────────────────────────────────────────────────────────
# Summarize 断路器
# ─────────────────────────────────────────────────────────────


class TestSummarizeCircuitBreaker:
    @pytest.fixture(autouse=True)
    def _isolate_contextvar(self):
        """Each test gets a fresh ContextVar value."""
        _set_failures(0)
        yield
        _set_failures(0)

    @pytest.mark.asyncio
    async def test_tripped_uses_fallback_in_process(self):
        """Circuit breaker open → process uses deterministic fallback."""
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES)
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm)
        result = await proc.process(ctx)
        assert result.metadata.get("summarize_fallback_used") is True
        assert _get_failures() == MAX_CONSECUTIVE_SUMMARIZE_FAILURES

    @pytest.mark.asyncio
    async def test_should_process_true_when_not_tripped(self):
        _set_failures(0)
        proc = SummarizeProcessor()
        ctx = _make_context()
        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.should_summarize",
            return_value=True,
        ):
            assert await proc.should_process(ctx) is True

    @pytest.mark.asyncio
    async def test_failure_increments_counter(self):
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm)

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors"
            ".summarize_processor.generate_structured_summary",
            side_effect=RuntimeError("API down"),
        ):
            result = await proc.process(ctx)

        assert _get_failures() == 1
        assert result.messages == ctx.messages

    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        _set_failures(2)
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm)

        mock_summary = AsyncMock()
        mock_summary.user_goal = "test goal for summary"

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors"
            ".summarize_processor.generate_structured_summary",
            return_value=([HumanMessage(content="summarized")], mock_summary),
        ):
            await proc.process(ctx)

        assert _get_failures() == 0

    @pytest.mark.asyncio
    async def test_circuit_trips_at_threshold(self):
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors"
            ".summarize_processor.generate_structured_summary",
            side_effect=RuntimeError("API down"),
        ):
            for _ in range(MAX_CONSECUTIVE_SUMMARIZE_FAILURES):
                ctx = _make_context(llm=mock_llm)
                await proc.process(ctx)

        assert _get_failures() == MAX_CONSECUTIVE_SUMMARIZE_FAILURES

        ctx = _make_context(llm=mock_llm)
        result = await proc.process(ctx)
        assert result.metadata.get("summarize_fallback_used") is True

    @pytest.mark.asyncio
    async def test_no_llm_uses_fallback_without_affecting_counter(self):
        _set_failures(1)
        proc = SummarizeProcessor()
        ctx = _make_context(llm=None)
        result = await proc.process(ctx)
        assert _get_failures() == 1
        assert result.metadata.get("summarize_fallback_used") is True

    @pytest.mark.asyncio
    async def test_below_threshold_still_processes(self):
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES - 1)
        proc = SummarizeProcessor()
        ctx = _make_context()
        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.should_summarize",
            return_value=True,
        ):
            assert await proc.should_process(ctx) is True

    @pytest.mark.asyncio
    async def test_failure_applies_deterministic_fallback(self):
        """LLM failure triggers deterministic fallback instead of returning unchanged."""
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        original_messages = [HumanMessage(content="original")]
        ctx = _make_context(llm=mock_llm, messages=original_messages)

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors"
            ".summarize_processor.generate_structured_summary",
            side_effect=ValueError("parse error"),
        ):
            result = await proc.process(ctx)

        assert result.metadata.get("summarize_fallback_used") is True
        assert result.structured_summary is not None
        assert _get_failures() == 1

    @pytest.mark.asyncio
    async def test_half_open_probe_attempts_llm(self):
        """After failure, the circuit breaker probes LLM on next request."""
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES)

        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        mock_summary = AsyncMock()
        mock_summary.user_goal = "recovered goal"

        ctx = _make_context(llm=mock_llm)

        # Fast forward time to pass cooldown
        with patch("time.time", return_value=time.time() + 3600):
            with patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors"
                ".summarize_processor.generate_structured_summary",
                return_value=([HumanMessage(content="summarized")], mock_summary),
            ):
                result = await proc.process(ctx)

            assert _get_failures() == 0
            assert result.structured_summary is mock_summary

    @pytest.mark.asyncio
    async def test_half_open_probe_failure_stays_open(self):
        """Half-open probe failure keeps circuit open and increments counter."""
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES)

        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm)

        # Fast forward time to pass cooldown
        with patch("time.time", return_value=time.time() + 3600):
            with patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors"
                ".summarize_processor.generate_structured_summary",
                side_effect=RuntimeError("still down"),
            ):
                result = await proc.process(ctx)

            assert _get_failures() == 1  # Reset to 0 then incremented to 1
            assert result.metadata.get("summarize_fallback_used") is True

    @pytest.mark.asyncio
    async def test_should_process_false_when_summary_present(self):
        proc = SummarizeProcessor()
        ctx = _make_context(structured_summary=MagicMock())
        assert await proc.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_skip_for_cache_preservation_resume(self):
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm, is_resume=True)

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.should_summarize",
            return_value=True,
        ):
            assert await proc.should_process(ctx) is True

        result = await proc.process(ctx)
        assert result.structured_summary is None

    @pytest.mark.asyncio
    async def test_success_records_last_msg_db_id(self):
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        mock_summary = MagicMock()
        mock_summary.user_goal = "goal"

        ctx = _make_context(llm=mock_llm, metadata={"last_message_db_id": "msg-123"})

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors"
            ".summarize_processor.generate_structured_summary",
            return_value=([HumanMessage(content="summarized")], mock_summary),
        ):
            result = await proc.process(ctx)

        assert result.last_summarized_message_id == "msg-123"

    @pytest.mark.asyncio
    async def test_fallback_records_last_msg_db_id(self):
        proc = SummarizeProcessor()
        ctx = _make_context(llm=None, metadata={"last_message_db_id": "msg-456"})
        result = await proc.process(ctx)
        assert result.last_summarized_message_id == "msg-456"

    @pytest.mark.asyncio
    async def test_auth_failure_opens_circuit_immediately(self):
        proc = SummarizeProcessor()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm)

        exc = RuntimeError("Unauthorized: invalid api key")

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors"
                ".summarize_processor.generate_structured_summary",
                side_effect=exc,
            ),
            patch("myrm_agent_harness.observability.auth_detector.detect_auth_failure", return_value=True),
        ):
            result = await proc.process(ctx)

        assert _get_failures() == MAX_CONSECUTIVE_SUMMARIZE_FAILURES
        assert result.metadata.get("summarize_fallback_used") is True


class TestClassifyErrorType:
    def test_auth_error(self):
        exc = RuntimeError("Unauthorized access")
        assert _classify_error_type(exc) == "auth"

    def test_permanent_error_model_not_found(self):
        exc = RuntimeError("Model not found")
        assert _classify_error_type(exc) == "permanent"

    def test_permanent_error_status_code(self):
        exc = MagicMock()
        exc.__str__ = lambda self: "server error"
        exc.status_code = 404
        assert _classify_error_type(exc) == "permanent"

    def test_transient_error_default(self):
        exc = RuntimeError("Connection timeout")
        assert _classify_error_type(exc) == "transient"


class TestSetFailuresErrorTypes:
    @pytest.fixture(autouse=True)
    def _isolate(self):
        _set_failures(0)
        yield
        _set_failures(0)

    def test_set_failures_permanent_type(self):
        _set_failures(3, "permanent")
        assert _get_failures() == 3

    def test_set_failures_transient_type(self):
        _set_failures(2, "transient")
        assert _get_failures() == 2


class TestBuildDeterministicSummary:
    def test_extracts_user_goal_and_last_action(self):
        messages = [
            HumanMessage(content="Please fix the bug in main.py"),
            AIMessage(content="I'll look at main.py now"),
        ]
        summary = _build_deterministic_summary(messages, {})
        assert "fix the bug" in summary.user_goal
        assert "main.py" in summary.last_action

    def test_truncates_long_goal(self):
        long_content = "x" * 500
        messages = [HumanMessage(content=long_content)]
        summary = _build_deterministic_summary(messages, {})
        assert summary.user_goal.endswith("…")

    def test_truncates_long_action(self):
        long_action = "y" * 200
        messages = [AIMessage(content=long_action)]
        summary = _build_deterministic_summary(messages, {})
        assert summary.last_action.endswith("…")

    def test_extracts_compacted_patterns(self):
        messages = [
            HumanMessage(content="do something"),
            ToolMessage(content="COMPACTED: bash(ls -la) output summary", tool_call_id="tc-1"),
        ]
        summary = _build_deterministic_summary(messages, {})
        assert any("bash" in a for a in summary.completed_actions)

    def test_uses_context_snapshot_path(self):
        messages = [HumanMessage(content="test")]
        metadata = {"context_snapshot_path": "/tmp/snapshot.json"}
        summary = _build_deterministic_summary(messages, metadata)
        assert summary.context_dump_path == "/tmp/snapshot.json"

    def test_no_messages_returns_defaults(self):
        summary = _build_deterministic_summary([], {})
        assert "Unable to extract" in summary.user_goal
        assert summary.last_action == ""

    def test_early_break_when_both_found(self):
        messages = [
            HumanMessage(content="first human"),
            AIMessage(content="first ai"),
            HumanMessage(content="second human"),
            AIMessage(content="second ai"),
        ]
        summary = _build_deterministic_summary(messages, {})
        assert "second human" in summary.user_goal
        assert "second ai" in summary.last_action
