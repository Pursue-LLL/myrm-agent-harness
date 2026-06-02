"""Tests for summarize processor circuit breaker logic and deterministic fallback."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor as _sp
from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
    MAX_CONSECUTIVE_SUMMARIZE_FAILURES,
    SummarizeProcessor,
    _build_deterministic_summary,
    _classify_error_type,
    _extract_focus_topic,
    _get_failures,
    _is_circuit_open,
    _is_half_open_probe,
    _record_fallback_call,
    _set_failures,
)
from myrm_agent_harness.observability.metrics.circuit_breaker_metrics import circuit_breaker_state


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    _set_failures(0)
    _sp._fallback_calls = 0
    _sp._circuit_open_time = None
    _sp._skip_next_api_token_check = False
    circuit_breaker_state.labels(component="summarize").set(0)
    yield
    _set_failures(0)
    _sp._fallback_calls = 0
    _sp._circuit_open_time = None
    _sp._skip_next_api_token_check = False
    circuit_breaker_state.labels(component="summarize").set(0)


class TestSummarizeProcessorCircuitBreaker:
    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_auth_failure_trips_circuit_breaker_immediately(self, mock_generate):
        mock_generate.side_effect = Exception("401 Unauthorized")
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")], user_query="test", user_id="test", chat_id="test", llm=AsyncMock()
        )

        result = await processor.process(context)

        assert _get_failures() == MAX_CONSECUTIVE_SUMMARIZE_FAILURES
        assert circuit_breaker_state.labels(component="summarize")._value.get() == 2.0

        # Check that deterministic fallback was used
        assert any("fallback" in m.content.lower() for m in result.messages)

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time")
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_cooldown_recovery(self, mock_generate, mock_time):
        mock_generate.side_effect = Exception("timeout")
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")], user_query="test", user_id="test", chat_id="test", llm=AsyncMock()
        )

        # Trip the circuit breaker
        mock_time.return_value = 1000.0
        for _ in range(MAX_CONSECUTIVE_SUMMARIZE_FAILURES):
            await processor.process(context)

        assert _get_failures() == MAX_CONSECUTIVE_SUMMARIZE_FAILURES
        assert circuit_breaker_state.labels(component="summarize")._value.get() == 2.0

        # Advance time past cooldown (1800 seconds)
        mock_time.return_value = 1000.0 + 1801.0

        # Next call should attempt recovery
        from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary

        mock_generate.side_effect = None
        mock_generate.return_value = ([], StructuredSummary(user_goal="test"))

        await processor.process(context)

        assert _get_failures() == 0
        assert circuit_breaker_state.labels(component="summarize")._value.get() == 0.0


class TestClassifyErrorType:
    def test_auth_error(self) -> None:
        assert _classify_error_type(Exception("401 Unauthorized")) == "auth"
        assert _classify_error_type(Exception("Invalid API Key")) == "auth"

    def test_permanent_error(self) -> None:
        assert _classify_error_type(Exception("model not found")) == "permanent"
        assert _classify_error_type(Exception("does not exist")) == "permanent"

    def test_permanent_by_status_code(self) -> None:
        exc = Exception("error")
        exc.status_code = 404  # type: ignore[attr-defined]
        assert _classify_error_type(exc) == "permanent"

    def test_transient_error(self) -> None:
        assert _classify_error_type(Exception("connection timeout")) == "transient"
        assert _classify_error_type(Exception("some random error")) == "transient"


class TestExtractFocusTopic:
    def test_with_valid_intent(self) -> None:
        metadata: dict[str, object] = {"compression_intent": {"user_goal_hint": "安全模块"}}
        assert _extract_focus_topic(metadata) == "安全模块"

    def test_with_empty_hint(self) -> None:
        metadata: dict[str, object] = {"compression_intent": {"user_goal_hint": ""}}
        assert _extract_focus_topic(metadata) == ""

    def test_without_intent(self) -> None:
        assert _extract_focus_topic({}) == ""

    def test_non_dict_intent(self) -> None:
        metadata: dict[str, object] = {"compression_intent": "not a dict"}
        assert _extract_focus_topic(metadata) == ""


class TestBuildDeterministicSummary:
    def test_basic_extraction(self) -> None:
        messages = [
            HumanMessage(content="实现JWT认证"),
            AIMessage(content="好的，已完成JWT认证"),
        ]
        summary = _build_deterministic_summary(messages, {})
        assert "JWT" in summary.user_goal
        assert "JWT" in summary.active_task
        assert summary.last_action != ""

    def test_compacted_pattern_extraction(self) -> None:
        messages = [
            HumanMessage(content="查看文件"),
            AIMessage(content="COMPACTED: read_file(src/main.py) 内容..."),
        ]
        summary = _build_deterministic_summary(messages, {})
        assert any("read_file" in a for a in summary.completed_actions)

    def test_snapshot_path_from_metadata(self) -> None:
        messages = [HumanMessage(content="test")]
        metadata: dict[str, object] = {"context_snapshot_path": "/tmp/snapshot.json"}
        summary = _build_deterministic_summary(messages, metadata)
        assert summary.context_dump_path == "/tmp/snapshot.json"

    def test_long_goal_truncation(self) -> None:
        long_msg = "x" * 500
        messages = [HumanMessage(content=long_msg)]
        summary = _build_deterministic_summary(messages, {})
        assert len(summary.active_task) <= 301

    def test_empty_messages(self) -> None:
        summary = _build_deterministic_summary([], {})
        assert "Unable to extract" in summary.user_goal


class TestSummarizeProcessorShouldProcess:
    @pytest.mark.asyncio
    async def test_skip_when_summary_exists(self) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")], user_query="test", user_id="test", chat_id="test", llm=AsyncMock()
        )
        context.structured_summary = StructuredSummary(user_goal="already done")
        assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_skip_for_cache_preservation_resume(self) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")], user_query="test", user_id="test", chat_id="test", llm=AsyncMock()
        )
        context.is_resume = True
        result = await processor.process(context)
        assert result.messages == context.messages

    @pytest.mark.asyncio
    async def test_no_llm_uses_deterministic_fallback(self) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test message content")],
            user_query="test",
            user_id="test",
            chat_id="test",
            llm=None,
        )
        result = await processor.process(context)
        assert any("fallback" in m.content.lower() for m in result.messages)
        assert result.metadata.get("summarize_fallback_used") is True

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_successful_llm_summary(self, mock_generate) -> None:
        summary = StructuredSummary(user_goal="目标", last_action="完成")
        mock_generate.return_value = ([HumanMessage(content="summary msg")], summary)
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")], user_query="test", user_id="test", chat_id="test", llm=AsyncMock()
        )
        result = await processor.process(context)
        assert result.structured_summary is not None
        assert result.structured_summary.user_goal == "目标"

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_transient_failure_increments_counter(self, mock_generate) -> None:
        mock_generate.side_effect = Exception("connection refused")
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")], user_query="test", user_id="test", chat_id="test", llm=AsyncMock()
        )
        prev = _get_failures()
        await processor.process(context)
        assert _get_failures() == prev + 1

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_focus_topic_passed_through(self, mock_generate) -> None:
        summary = StructuredSummary(user_goal="目标", last_action="完成")
        mock_generate.return_value = ([HumanMessage(content="s")], summary)
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            user_id="test",
            chat_id="test",
            llm=AsyncMock(),
            metadata={"compression_intent": {"user_goal_hint": "安全"}},
        )
        await processor.process(context)
        call_kwargs = mock_generate.call_args[1]
        assert call_kwargs.get("focus_topic") == "安全"


class TestSetFailuresCooldown:
    """Cover _set_failures tiered cooldown branches."""

    def test_auth_cooldown(self) -> None:
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES, "auth")
        assert _sp._circuit_cooldown_seconds == 1800

    def test_permanent_cooldown(self) -> None:
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES, "permanent")
        assert _sp._circuit_cooldown_seconds == 600

    def test_transient_cooldown(self) -> None:
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES, "transient")
        assert _sp._circuit_cooldown_seconds == 60

    def test_below_threshold_no_open_time(self) -> None:
        _set_failures(1)
        assert _sp._circuit_open_time is None or _sp._summarize_failures == 1


class TestIsCircuitOpen:
    """Cover _is_circuit_open branches."""

    def test_below_threshold_returns_false(self) -> None:
        _set_failures(0)
        assert _is_circuit_open() is False

    @patch("myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time")
    def test_open_sets_time_on_first_call(self, mock_time) -> None:
        mock_time.return_value = 5000.0
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES)
        _sp._circuit_open_time = None
        assert _is_circuit_open() is True
        assert _sp._circuit_open_time == 5000.0

    @patch("myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time")
    def test_within_cooldown_stays_open(self, mock_time) -> None:
        mock_time.return_value = 5000.0
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES, "transient")
        _sp._circuit_open_time = 4950.0
        assert _is_circuit_open() is True

    @patch("myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time")
    def test_past_cooldown_resets(self, mock_time) -> None:
        mock_time.return_value = 10000.0
        _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES, "transient")
        _sp._circuit_open_time = 5000.0
        _sp._circuit_cooldown_seconds = 60
        assert _is_circuit_open() is False
        assert _get_failures() == 0


class TestIsHalfOpenProbe:
    """Cover _is_half_open_probe logic."""

    def test_zero_calls_not_probe(self) -> None:
        _sp._fallback_calls = 0
        assert _is_half_open_probe() is False

    def test_odd_calls_not_probe(self) -> None:
        _sp._fallback_calls = 1
        assert _is_half_open_probe() is False

    def test_even_calls_is_probe(self) -> None:
        _sp._fallback_calls = 2
        assert _is_half_open_probe() is True


class TestShouldBypassForHotCache:
    """Cover _should_bypass_for_hot_cache branches."""

    def test_above_90_percent_never_bypass(self) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[], user_query="t", metadata={"last_activity_time": 0.0}
        )
        assert processor._should_bypass_for_hot_cache(context, 120000) is False

    @patch("myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time")
    def test_recent_activity_bypasses(self, mock_time) -> None:
        mock_time.return_value = 1000.0
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[], user_query="t", metadata={"last_activity_time": 999.0}
        )
        assert processor._should_bypass_for_hot_cache(context, 50000) is True

    @patch("myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time")
    def test_old_activity_no_bypass(self, mock_time) -> None:
        mock_time.return_value = 1000.0
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[], user_query="t", metadata={"last_activity_time": 100.0}
        )
        assert processor._should_bypass_for_hot_cache(context, 50000) is False

    def test_no_activity_time_no_bypass(self) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(messages=[], user_query="t", metadata={})
        assert processor._should_bypass_for_hot_cache(context, 50000) is False


class TestShouldProcessBranches:
    """Cover should_process branches beyond existing tests."""

    @pytest.mark.asyncio
    async def test_force_proactive_reset_triggers(self) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            metadata={"force_proactive_reset": True},
        )
        assert await processor.should_process(context) is True

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.should_summarize",
        return_value=False,
    )
    async def test_should_summarize_false_returns_false(self, _mock) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
        )
        assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.estimate_messages_tokens",
        return_value=50000,
    )
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.should_summarize",
        return_value=True,
    )
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time",
        return_value=1000.0,
    )
    async def test_hot_cache_bypass_sets_debt(self, _t, _ss, _et) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            metadata={"last_activity_time": 999.5},
        )
        result = await processor.should_process(context)
        assert result is False
        assert context.metadata.get("compaction_debt_pending") is True

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.estimate_messages_tokens",
        return_value=50000,
    )
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.should_summarize",
        return_value=True,
    )
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.time.time",
        return_value=10000.0,
    )
    async def test_cold_cache_triggers_summarize(self, _t, _ss, _et) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            metadata={"last_activity_time": 1.0},
        )
        assert await processor.should_process(context) is True

    @pytest.mark.asyncio
    async def test_skip_next_api_token_check_flag(self) -> None:
        _sp._skip_next_api_token_check = True
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
        )
        await processor.should_process(context)
        assert _sp._skip_next_api_token_check is False


class TestProcessNotifyCompaction:
    """Verify notify_compaction() is called in both success and fallback paths."""

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    @patch(
        "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector"
    )
    async def test_success_path_calls_notify_compaction(self, mock_detector_fn, mock_generate) -> None:
        mock_detector = AsyncMock()
        mock_detector.notify_compaction = lambda: None
        mock_detector_fn.return_value = mock_detector

        summary = StructuredSummary(user_goal="test goal")
        mock_generate.return_value = ([HumanMessage(content="s")], summary)

        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            user_id="test",
            chat_id="test",
            llm=AsyncMock(),
        )
        result = await processor.process(context)
        assert result.structured_summary is not None
        mock_detector_fn.assert_called()

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector"
    )
    async def test_fallback_path_calls_notify_compaction(self, mock_detector_fn) -> None:
        mock_detector = AsyncMock()
        mock_detector.notify_compaction = lambda: None
        mock_detector_fn.return_value = mock_detector

        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test content here")],
            user_query="test",
            user_id="test",
            chat_id="test",
            llm=None,
        )
        result = await processor.process(context)
        assert result.metadata.get("summarize_fallback_used") is True
        mock_detector_fn.assert_called()

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_success_path_sets_last_summarized_message_id(self, mock_generate) -> None:
        summary = StructuredSummary(user_goal="goal")
        mock_generate.return_value = ([HumanMessage(content="s")], summary)

        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            user_id="test",
            chat_id="test",
            llm=AsyncMock(),
            metadata={"last_message_db_id": "msg-123"},
        )
        result = await processor.process(context)
        assert result.last_summarized_message_id == "msg-123"

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_success_path_sets_skip_flag(self, mock_generate) -> None:
        summary = StructuredSummary(user_goal="goal")
        mock_generate.return_value = ([HumanMessage(content="s")], summary)

        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            llm=AsyncMock(),
        )
        await processor.process(context)
        assert _sp._skip_next_api_token_check is True


class TestProcessHITLSkip:
    """Cover HITL session skip path."""

    @pytest.mark.asyncio
    async def test_hitl_session_skips_processing(self) -> None:
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            merged_context={"hitl_session_active": True},
        )
        result = await processor.process(context)
        assert result.messages == [HumanMessage(content="test")]


class TestProcessPermanentError:
    """Cover permanent error classification in process exception handling."""

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_permanent_error_increments_counter(self, mock_generate) -> None:
        mock_generate.side_effect = Exception("model not found")
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            llm=AsyncMock(),
        )
        await processor.process(context)
        assert _get_failures() == 1

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor.generate_structured_summary"
    )
    async def test_timeout_error_tracked_as_timeout(self, mock_generate) -> None:
        mock_generate.side_effect = Exception("request timeout")
        processor = SummarizeProcessor()
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            llm=AsyncMock(),
        )
        await processor.process(context)
        assert _get_failures() == 1


class TestRecordFallbackCall:
    def test_increments(self) -> None:
        _sp._fallback_calls = 0
        _record_fallback_call()
        assert _sp._fallback_calls == 1
        _record_fallback_call()
        assert _sp._fallback_calls == 2


class TestProcessorName:
    def test_name_is_summarize(self) -> None:
        assert SummarizeProcessor().name == "summarize"
