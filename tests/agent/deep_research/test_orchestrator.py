"""Deep Research orchestrator tests — config, helpers, and orchestration logic."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from myrm_agent_harness.agent.deep_research.config import (
    DeepResearchConfig,
    DeepResearchPhase,
    ToolCategory,
)
from myrm_agent_harness.agent.deep_research.helpers import (
    DeepResearchResult,
    accumulate_usage,
    compact_orch_messages,
    detect_reasoning_model,
    estimate_cost,
    extract_tool_calls,
    get_model_context_limit,
    truncate_for_orchestrator,
)
from myrm_agent_harness.agent.deep_research.orchestrator import DeepResearchOrchestrator
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.meta_tools.clarification import AskQuestionInput

if TYPE_CHECKING:
    pass


# =========================================================================
# Config tests
# =========================================================================


class TestDeepResearchConfig:
    def test_defaults(self):
        cfg = DeepResearchConfig()
        assert cfg.max_cycles == 8
        assert cfg.max_cycles_reasoning == 4
        assert cfg.max_duration_seconds == 1800
        assert cfg.min_context_tokens == 50_000
        assert cfg.max_concurrent_agents == 3
        assert cfg.enable_clarification is True
        assert cfg.report_timeout_seconds == 300
        assert cfg.llm_call_timeout_seconds == 120
        assert cfg.max_research_agent_turns == 16
        assert cfg.research_agent_timeout_seconds == 600
        assert cfg.max_report_context_chars == 100_000

    def test_frozen(self):
        cfg = DeepResearchConfig()
        with pytest.raises(AttributeError):
            cfg.max_cycles = 10  # type: ignore[misc]

    def test_custom_values(self):
        cfg = DeepResearchConfig(max_cycles=4, research_agent_timeout_seconds=900)
        assert cfg.max_cycles == 4
        assert cfg.research_agent_timeout_seconds == 900

    def test_tool_categories(self):
        cfg = DeepResearchConfig()
        assert ToolCategory.SEARCH in cfg.allowed_tool_categories
        assert ToolCategory.CODE_EXEC not in cfg.allowed_tool_categories

    def test_phase_enum(self):
        assert DeepResearchPhase.CLARIFY == "clarify"
        assert DeepResearchPhase.REPORT == "report"


# =========================================================================
# Helper function tests
# =========================================================================


class TestDetectReasoningModel:
    def test_o1_model(self):
        llm = MagicMock()
        llm.model_name = "o1-preview"
        assert detect_reasoning_model(llm) is True

    def test_o3_model(self):
        llm = MagicMock()
        llm.model_name = "o3-mini"
        assert detect_reasoning_model(llm) is True

    def test_deepseek_reasoning(self):
        llm = MagicMock()
        llm.model_name = "deepseek-r1"
        assert detect_reasoning_model(llm) is True

    def test_claude_37(self):
        llm = MagicMock()
        llm.model_name = "claude-3-7-sonnet"
        assert detect_reasoning_model(llm) is True

    def test_gpt4o_not_reasoning(self):
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        assert detect_reasoning_model(llm) is False

    def test_no_model_name(self):
        llm = MagicMock(spec=[])
        assert detect_reasoning_model(llm) is False


class TestGetModelContextLimit:
    def test_direct_attribute(self):
        llm = MagicMock()
        llm.n_ctx = 128000
        llm.model_max_context_length = None
        llm.max_input_tokens = None
        assert get_model_context_limit(llm) == 128000

    def test_max_input_tokens(self):
        llm = MagicMock()
        llm.n_ctx = None
        llm.model_max_context_length = None
        llm.max_input_tokens = 200000
        assert get_model_context_limit(llm) == 200000

    def test_litellm_fallback(self):
        llm = MagicMock()
        llm.n_ctx = None
        llm.model_max_context_length = None
        llm.max_input_tokens = None
        llm.model_name = "gpt-4o"
        llm.model = None

        mock_litellm = MagicMock()
        mock_litellm.get_model_info.return_value = {"max_input_tokens": 128000}
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            result = get_model_context_limit(llm)
            assert result == 128000

    def test_no_info_returns_none(self):
        llm = MagicMock(spec=[])
        assert get_model_context_limit(llm) is None

    def test_zero_value_skipped(self):
        llm = MagicMock()
        llm.n_ctx = 0
        llm.model_max_context_length = 0
        llm.max_input_tokens = 0
        llm.model_name = ""
        llm.model = ""
        assert get_model_context_limit(llm) is None


class TestAccumulateUsage:
    def test_accumulates_correctly(self):
        result = DeepResearchResult()
        msg = MagicMock()
        msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        accumulate_usage(result, msg)
        assert result.total_input_tokens == 100
        assert result.total_output_tokens == 50

    def test_accumulates_multiple(self):
        result = DeepResearchResult()
        msg1 = MagicMock()
        msg1.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        msg2 = MagicMock()
        msg2.usage_metadata = {"input_tokens": 200, "output_tokens": 80}
        accumulate_usage(result, msg1)
        accumulate_usage(result, msg2)
        assert result.total_input_tokens == 300
        assert result.total_output_tokens == 130

    def test_no_usage_metadata(self):
        result = DeepResearchResult()
        msg = MagicMock(spec=[])
        accumulate_usage(result, msg)
        assert result.total_input_tokens == 0

    def test_non_dict_usage(self):
        result = DeepResearchResult()
        msg = MagicMock()
        msg.usage_metadata = "not a dict"
        accumulate_usage(result, msg)
        assert result.total_input_tokens == 0


class TestEstimateCost:
    def test_calculates_cost(self):
        result = DeepResearchResult(total_input_tokens=1000, total_output_tokens=500)
        mock_litellm = MagicMock()
        mock_litellm.cost_per_token.return_value = (0.01, 0.02)
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            estimate_cost(result, "gpt-4o")
            assert result.estimated_cost_usd == 0.03

    def test_no_tokens_skips(self):
        result = DeepResearchResult()
        estimate_cost(result, "gpt-4o")
        assert result.estimated_cost_usd == 0.0

    def test_no_model_name_skips(self):
        result = DeepResearchResult(total_input_tokens=100, total_output_tokens=50)
        estimate_cost(result, "")
        assert result.estimated_cost_usd == 0.0

    def test_litellm_error_graceful(self):
        result = DeepResearchResult(total_input_tokens=100, total_output_tokens=50)
        mock_litellm = MagicMock()
        mock_litellm.cost_per_token.side_effect = Exception("Unknown model")
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            estimate_cost(result, "unknown-model")
            assert result.estimated_cost_usd == 0.0


class TestTruncateForOrchestrator:
    def test_short_text_unchanged(self):
        text = "Short result"
        assert truncate_for_orchestrator(text) == text

    def test_long_text_truncated(self):
        text = "x" * 20_000
        result = truncate_for_orchestrator(text)
        assert len(result) < 20_000
        assert "[Truncated" in result

    def test_exactly_at_limit(self):
        text = "x" * 12_000
        assert truncate_for_orchestrator(text) == text


class TestExtractToolCalls:
    def test_extracts_tool_calls(self):
        msg = MagicMock(spec=AIMessage)
        msg.tool_calls = [
            {"id": "tc1", "name": "dispatch_research", "args": {"task": "test"}},
        ]
        result = extract_tool_calls(msg)
        assert len(result) == 1
        assert result[0]["name"] == "dispatch_research"

    def test_no_tool_calls(self):
        msg = MagicMock(spec=AIMessage)
        msg.tool_calls = []
        result = extract_tool_calls(msg)
        assert result == []

    def test_no_attribute(self):
        msg = MagicMock(spec=[])
        result = extract_tool_calls(msg)
        assert result == []


# =========================================================================
# Compact orch_messages tests
# =========================================================================


class TestCompactOrchMessages:
    def test_under_budget_no_change(self):
        messages: list[BaseMessage] = [
            SystemMessage(content="system"),
            HumanMessage(content="query"),
            AIMessage(content="response"),
        ]
        original_len = len(messages)
        compact_orch_messages(messages)
        assert len(messages) == original_len
        assert str(messages[2].content) == "response"

    def test_over_budget_compacts_old_tool_messages(self):
        long_content = "x" * 50_000
        messages: list[BaseMessage] = [
            SystemMessage(content="system"),
            HumanMessage(content="query"),
        ]
        for i in range(8):
            messages.append(
                AIMessage(
                    content=f"response_{i}",
                    tool_calls=[
                        {"id": f"tc_{i}", "name": "dispatch_research", "args": {}}
                    ],
                )
            )
            messages.append(ToolMessage(content=long_content, tool_call_id=f"tc_{i}"))

        total_before = sum(len(str(m.content)) for m in messages)
        assert total_before > 200_000

        compact_orch_messages(messages)

        total_after = sum(len(str(m.content)) for m in messages)
        assert total_after < total_before

        compacted_count = sum(
            1
            for m in messages
            if isinstance(m, ToolMessage) and "compacted" in str(m.content)
        )
        assert compacted_count > 0

    def test_preserves_recent_messages(self):
        long_content = "x" * 50_000
        messages: list[BaseMessage] = [SystemMessage(content="system")]

        for i in range(20):
            messages.append(
                AIMessage(
                    content=f"r_{i}",
                    tool_calls=[{"id": f"tc_{i}", "name": "test", "args": {}}],
                )
            )
            messages.append(ToolMessage(content=long_content, tool_call_id=f"tc_{i}"))

        compact_orch_messages(messages)

        recent_tool_msgs = [m for m in messages[-12:] if isinstance(m, ToolMessage)]
        for msg in recent_tool_msgs:
            assert "compacted" not in str(msg.content)

    def test_preserves_tool_call_id(self):
        messages: list[BaseMessage] = [
            SystemMessage(content="s" * 100_000),
            AIMessage(
                content="r", tool_calls=[{"id": "tc_old", "name": "test", "args": {}}]
            ),
            ToolMessage(content="x" * 50_000, tool_call_id="tc_old"),
        ] + [HumanMessage(content="pad")] * 15

        compact_orch_messages(messages)

        compacted_msg = messages[2]
        assert isinstance(compacted_msg, ToolMessage)
        assert compacted_msg.tool_call_id == "tc_old"

    def test_idempotent(self):
        messages: list[BaseMessage] = [
            SystemMessage(content="s" * 100_000),
            ToolMessage(content="x" * 50_000, tool_call_id="tc1"),
        ] + [HumanMessage(content="pad")] * 15

        compact_orch_messages(messages)
        first_pass = [str(m.content) for m in messages]

        compact_orch_messages(messages)
        second_pass = [str(m.content) for m in messages]

        assert first_pass == second_pass


# =========================================================================
# Format research context tests
# =========================================================================


class TestFormatResearchContext:
    def _make_orchestrator(self, **kwargs: object) -> DeepResearchOrchestrator:
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        return DeepResearchOrchestrator(llm=llm, config=DeepResearchConfig(**kwargs))

    def test_empty_results(self):
        orch = self._make_orchestrator()
        assert orch._format_research_context() == ""

    def test_single_result(self):
        orch = self._make_orchestrator()
        orch._result.agent_results = [
            {"task": "Test task", "result": "Found something"}
        ]
        ctx = orch._format_research_context()
        assert "Test task" in ctx
        assert "Found something" in ctx

    def test_within_limit(self):
        orch = self._make_orchestrator(max_report_context_chars=100_000)
        orch._result.agent_results = [
            {"task": f"Task {i}", "result": f"Result {i}"} for i in range(5)
        ]
        ctx = orch._format_research_context()
        assert "Task 1" in ctx
        assert "Task 5" in ctx

    def test_exceeds_limit_truncates_earliest(self):
        orch = self._make_orchestrator(max_report_context_chars=500)
        orch._result.agent_results = [
            {"task": f"Task {i}", "result": "x" * 200} for i in range(5)
        ]
        ctx = orch._format_research_context()
        assert len(ctx) <= 600
        assert "Task 5" in ctx

    def test_truncation_marker_present(self):
        orch = self._make_orchestrator(max_report_context_chars=300)
        orch._result.agent_results = [
            {"task": f"Task {i}", "result": "x" * 200} for i in range(3)
        ]
        ctx = orch._format_research_context()
        assert "[Truncated" in ctx or "Task 3" in ctx


# =========================================================================
# DeepResearchResult tests
# =========================================================================


class TestDeepResearchResult:
    def test_defaults(self):
        r = DeepResearchResult()
        assert r.report == ""
        assert r.cycle_count == 0
        assert r.total_input_tokens == 0
        assert r.estimated_cost_usd == 0.0
        assert r.was_cancelled is False
        assert r.error is None

    def test_mutable_fields(self):
        r = DeepResearchResult()
        r.agent_results.append({"task": "t1", "result": "r1"})
        assert len(r.agent_results) == 1

    def test_independent_instances(self):
        r1 = DeepResearchResult()
        r2 = DeepResearchResult()
        r1.agent_results.append({"task": "t1", "result": "r1"})
        assert len(r2.agent_results) == 0


# =========================================================================
# Orchestrator integration tests (mock LLM)
# =========================================================================


class TestOrchestratorRun:
    def _make_llm(self, responses: list[AIMessage]) -> MagicMock:
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        llm.model = "gpt-4o"
        llm.n_ctx = None
        llm.model_max_context_length = None
        llm.max_input_tokens = None

        bound = MagicMock()
        call_count = 0

        async def mock_ainvoke(messages: list[BaseMessage]) -> AIMessage:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        bound.ainvoke = mock_ainvoke
        llm.bind_tools = MagicMock(return_value=bound)
        llm.ainvoke = AsyncMock(side_effect=responses)

        return llm

    @pytest.mark.asyncio
    async def test_context_too_small(self):
        llm = MagicMock()
        llm.n_ctx = 10_000
        llm.model_name = "small-model"

        orch = DeepResearchOrchestrator(llm=llm)
        events = [e async for e in orch.run("test query")]

        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) == 1
        assert "ContextTooSmall" in str(error_events[0].get("error_type", ""))

    @pytest.mark.asyncio
    async def test_clarification_skipped_when_finalize(self):
        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "finalize_report", "args": {}}],
        )
        plan_response = AIMessage(content="1. Research topic A")
        plan_response.usage_metadata = {"input_tokens": 50, "output_tokens": 20}

        llm = self._make_llm([finalize_response])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "Final report"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        orch = DeepResearchOrchestrator(
            llm=llm, config=DeepResearchConfig(enable_clarification=True, max_cycles=1)
        )

        events = [e async for e in orch.run("detailed query with enough context")]
        step_events = [e for e in events if e.get("type") == "tasks_steps"]
        assert len(step_events) >= 1

    @pytest.mark.asyncio
    async def test_clarification_callback_invoked(self):
        clarify_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tc_ask",
                    "name": "ask_question_tool",
                    "args": {
                        "title": "Clarification needed",
                        "questions": [
                            {
                                "id": "q1",
                                "prompt": "What specific aspect?",
                                "options": [{"id": "opt1", "label": "Performance"}],
                                "allow_multiple": False,
                            }
                        ],
                    },
                }
            ],
        )
        clarify_response.usage_metadata = {"input_tokens": 30, "output_tokens": 10}

        finalize_in_research = AIMessage(
            content="",
            tool_calls=[{"id": "tc_fin", "name": "finalize_report", "args": {}}],
        )

        plan_response = AIMessage(content="1. Do research")
        plan_response.usage_metadata = {"input_tokens": 50, "output_tokens": 20}

        callback_called = False

        async def on_clarify(form: AskQuestionInput) -> str | None:
            nonlocal callback_called
            callback_called = True
            assert form.title == "Clarification needed"
            assert len(form.questions) == 1
            assert form.questions[0].options[0].label == "Performance"
            combined = " ".join(q.prompt for q in form.questions)
            assert "aspect" in combined
            return {"q1": "Performance"}

        llm = self._make_llm([clarify_response, finalize_in_research])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "Report"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        orch = DeepResearchOrchestrator(
            llm=llm, config=DeepResearchConfig(max_cycles=1), on_clarify=on_clarify
        )

        _ = [e async for e in orch.run("query")]
        assert callback_called

    @pytest.mark.asyncio
    async def test_clarification_fallback_raw_text(self):
        clarify_response = AIMessage(content="What specific aspect?")
        clarify_response.usage_metadata = {"input_tokens": 30, "output_tokens": 10}

        finalize_in_research = AIMessage(
            content="",
            tool_calls=[{"id": "tc_fin", "name": "finalize_report", "args": {}}],
        )

        plan_response = AIMessage(content="1. Do research")
        plan_response.usage_metadata = {"input_tokens": 50, "output_tokens": 20}

        callback_called = False

        async def on_clarify(form: AskQuestionInput) -> str | None:
            nonlocal callback_called
            callback_called = True
            assert form.title is None
            assert len(form.questions) == 1
            assert form.questions[0].prompt == "What specific aspect?"
            return "I want to know about performance"

        llm = self._make_llm([clarify_response, finalize_in_research])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "Report"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        orch = DeepResearchOrchestrator(
            llm=llm, config=DeepResearchConfig(max_cycles=1), on_clarify=on_clarify
        )

        _ = [e async for e in orch.run("query")]
        assert callback_called

    @pytest.mark.asyncio
    async def test_cancellation_stops_execution(self):
        cancel_token = MagicMock()
        cancel_token.is_cancelled = True

        plan_response = AIMessage(content="plan")
        plan_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        llm = MagicMock()
        llm.model_name = "gpt-4o"
        llm.n_ctx = None
        llm.model_max_context_length = None
        llm.max_input_tokens = None

        bound = MagicMock()

        async def mock_ainvoke(messages: list[BaseMessage]) -> AIMessage:
            return AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "finalize_report", "args": {}}],
            )

        bound.ainvoke = mock_ainvoke
        llm.bind_tools = MagicMock(return_value=bound)
        llm.ainvoke = AsyncMock(return_value=plan_response)

        orch = DeepResearchOrchestrator(
            llm=llm,
            config=DeepResearchConfig(enable_clarification=False),
            cancel_token=cancel_token,
        )

        _ = [e async for e in orch.run("query")]
        assert orch.result.was_cancelled is True

    @pytest.mark.asyncio
    async def test_report_token_estimation_fallback(self):
        plan_response = AIMessage(content="1. Plan")
        plan_response.usage_metadata = {"input_tokens": 100, "output_tokens": 30}

        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc_fin", "name": "finalize_report", "args": {}}],
        )

        llm = self._make_llm([finalize_response])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        report_text = "x" * 4000

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = report_text
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        orch = DeepResearchOrchestrator(
            llm=llm, config=DeepResearchConfig(enable_clarification=False, max_cycles=1)
        )

        _ = [e async for e in orch.run("query")]

        assert orch.result.total_output_tokens > 0
        assert orch.result.total_output_tokens >= len(report_text) // 4

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self):
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        llm.n_ctx = None
        llm.model_max_context_length = None
        llm.max_input_tokens = None

        bound = MagicMock()

        async def mock_ainvoke(messages: list[BaseMessage]) -> AIMessage:
            raise TimeoutError("LLM timeout")

        bound.ainvoke = mock_ainvoke
        llm.bind_tools = MagicMock(return_value=bound)

        orch = DeepResearchOrchestrator(
            llm=llm,
            config=DeepResearchConfig(
                enable_clarification=True, llm_call_timeout_seconds=1
            ),
        )

        events = [e async for e in orch.run("query")]
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) == 1
        assert orch.result.error is not None

    @pytest.mark.asyncio
    async def test_progress_estimation(self):
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm)
        orch._start_time = 1.0

        orch._phase = DeepResearchPhase.CLARIFY
        assert orch._estimate_progress() == 3

        orch._phase = DeepResearchPhase.PLAN
        assert orch._estimate_progress() == 10

        orch._phase = DeepResearchPhase.RESEARCH
        orch._result.cycle_count = 0
        assert orch._estimate_progress() == 15

        orch._result.cycle_count = 4
        progress = orch._estimate_progress()
        assert 15 < progress < 85

        orch._phase = DeepResearchPhase.REPORT
        assert orch._estimate_progress() == 90

    @pytest.mark.asyncio
    async def test_budget_checks(self):
        cfg = DeepResearchConfig(max_budget_usd=1.0, budget_warning_threshold=0.8)
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm, config=cfg)

        orch._result.estimated_cost_usd = 0.5
        assert orch._is_over_budget() is False
        assert orch._is_budget_warning() is False

        orch._result.estimated_cost_usd = 0.85
        assert orch._is_over_budget() is False
        assert orch._is_budget_warning() is True

        orch._result.estimated_cost_usd = 1.5
        assert orch._is_over_budget() is True

    @pytest.mark.asyncio
    async def test_budget_zero_disabled(self):
        cfg = DeepResearchConfig(max_budget_usd=0.0)
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm, config=cfg)
        orch._result.estimated_cost_usd = 999.0
        assert orch._is_over_budget() is False
        assert orch._is_budget_warning() is False

    @pytest.mark.asyncio
    async def test_accumulate_child_usage(self):
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm)

        orch._accumulate_child_usage(
            {"usage": {"input_tokens": 100, "output_tokens": 50}}
        )
        assert orch._result.total_input_tokens == 100
        assert orch._result.total_output_tokens == 50

        orch._accumulate_child_usage(
            {"usage": {"input_tokens": 200, "output_tokens": 80}}
        )
        assert orch._result.total_input_tokens == 300
        assert orch._result.total_output_tokens == 130

        orch._accumulate_child_usage({"other_field": "value"})
        assert orch._result.total_input_tokens == 300

        orch._accumulate_child_usage({"usage": "not_a_dict"})
        assert orch._result.total_input_tokens == 300

    @pytest.mark.asyncio
    async def test_make_event_structure(self):
        llm = MagicMock()
        llm.model_name = "gpt-4o"

        orch = DeepResearchOrchestrator(llm=llm)
        event = orch._make_event(AgentEventType.MESSAGE, "msg-123", data="hello")
        assert event["type"] == "message"
        assert event["messageId"] == "msg-123"
        assert event["data"] == "hello"

    @pytest.mark.asyncio
    async def test_update_cost_estimate(self):
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        llm.model = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm)
        orch._result.total_input_tokens = 1000
        orch._result.total_output_tokens = 500
        mock_litellm = MagicMock()
        mock_litellm.cost_per_token.return_value = (0.01, 0.02)
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            orch._update_cost_estimate()
            assert orch._result.estimated_cost_usd > 0

    @pytest.mark.asyncio
    async def test_is_cancelled_and_timed_out(self):
        import time

        cancel_token = MagicMock()
        cancel_token.is_cancelled = False
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(
            llm=llm,
            cancel_token=cancel_token,
            config=DeepResearchConfig(max_duration_seconds=1),
        )
        orch._start_time = time.time()
        assert orch._is_cancelled() is False
        assert orch._is_timed_out() is False

        cancel_token.is_cancelled = True
        assert orch._is_cancelled() is True

        orch._start_time = time.time() - 10
        assert orch._is_timed_out() is True

    @pytest.mark.asyncio
    async def test_dispatch_research_single_agent(self):
        """Test _dispatch_research_agents with a mocked sub-agent."""
        import asyncio

        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm, parent_tools=[])
        orch._start_time = 1.0

        mock_agent = MagicMock()

        async def mock_run(query, chat_history, context, cancel_token):
            yield {"type": AgentEventType.MESSAGE.value, "data": "Research finding"}
            yield {
                "type": AgentEventType.MESSAGE_END.value,
                "usage": {"input_tokens": 50, "output_tokens": 20},
            }

        mock_agent.run = mock_run

        with (
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.build_standalone_agent",
                return_value=mock_agent,
            ),
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.filter_tools",
                return_value=[],
            ),
        ):
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            results = await orch._dispatch_research_agents(
                tasks=[{"task": "Find info about X", "tc_id": "tc1"}],
                message_id="msg-1",
                event_queue=queue,
            )

        assert len(results) == 1
        assert "Research finding" in results[0]
        assert orch._result.total_input_tokens == 50
        assert orch._result.total_output_tokens == 20

    @pytest.mark.asyncio
    async def test_dispatch_research_agent_error(self):
        """Test _dispatch_research_agents error handling."""
        import asyncio

        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm, parent_tools=[])
        orch._start_time = 1.0

        with (
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.build_standalone_agent",
                side_effect=Exception("Agent creation failed"),
            ),
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.filter_tools",
                return_value=[],
            ),
        ):
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            results = await orch._dispatch_research_agents(
                tasks=[{"task": "Task A", "tc_id": "tc1"}],
                message_id="msg-1",
                event_queue=queue,
            )

        assert len(results) == 1
        assert "failed" in results[0].lower()

    @pytest.mark.asyncio
    async def test_full_research_cycle_with_dispatch(self):
        """Test a full orchestrator run that includes dispatch + finalize."""

        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc_fin", "name": "finalize_report", "args": {}}],
        )
        dispatch_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tc_d1",
                    "name": "dispatch_research",
                    "args": {"task": "Research AI"},
                }
            ],
        )

        plan_response = AIMessage(content="1. Research AI models")
        plan_response.usage_metadata = {"input_tokens": 100, "output_tokens": 30}

        call_idx = 0

        async def mock_bound_ainvoke(messages: list[BaseMessage]) -> AIMessage:
            nonlocal call_idx
            call_idx += 1
            if call_idx == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc_skip", "name": "finalize_report", "args": {}}
                    ],
                )
            if call_idx == 2:
                dispatch_response.usage_metadata = {
                    "input_tokens": 80,
                    "output_tokens": 20,
                }
                return dispatch_response
            finalize_response.usage_metadata = {"input_tokens": 40, "output_tokens": 10}
            return finalize_response

        llm = MagicMock()
        llm.model_name = "gpt-4o"
        llm.model = "gpt-4o"
        llm.n_ctx = None
        llm.model_max_context_length = None
        llm.max_input_tokens = None

        bound = MagicMock()
        bound.ainvoke = mock_bound_ainvoke
        llm.bind_tools = MagicMock(return_value=bound)
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "# AI Models Report"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        mock_agent = MagicMock()

        async def mock_agent_run(query, chat_history, context, cancel_token):
            yield {"type": AgentEventType.MESSAGE.value, "data": "AI is evolving fast."}
            yield {
                "type": AgentEventType.MESSAGE_END.value,
                "usage": {"input_tokens": 30, "output_tokens": 15},
            }

        mock_agent.run = mock_agent_run

        with (
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.build_standalone_agent",
                return_value=mock_agent,
            ),
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.filter_tools",
                return_value=[],
            ),
        ):
            orch = DeepResearchOrchestrator(
                llm=llm,
                config=DeepResearchConfig(enable_clarification=True, max_cycles=2),
                parent_tools=[],
            )

            events = [
                e async for e in orch.run("Research AI models", message_id="msg-test")
            ]

        event_types = [e.get("type") for e in events]
        assert "tasks_steps" in event_types
        assert "message" in event_types
        assert "message_end" in event_types
        assert orch.result.cycle_count >= 1
        assert orch.result.report == "# AI Models Report"

    @pytest.mark.asyncio
    async def test_report_phase_injects_integrity_rules(self):
        """Verify FINAL_REPORT_PROMPT with Information Integrity Rules is injected into the report LLM call."""

        plan_response = AIMessage(content="1. Research topic")
        plan_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "finalize_report", "args": {}}],
        )
        finalize_response.usage_metadata = {"input_tokens": 20, "output_tokens": 5}

        llm = MagicMock()
        llm.model_name = "gpt-4o"
        llm.model = "gpt-4o"
        llm.n_ctx = None
        llm.model_max_context_length = None
        llm.max_input_tokens = None

        bound = MagicMock()

        async def mock_bound_ainvoke(messages: list[BaseMessage]) -> AIMessage:
            return finalize_response

        bound.ainvoke = mock_bound_ainvoke
        llm.bind_tools = MagicMock(return_value=bound)
        llm.ainvoke = AsyncMock(return_value=plan_response)

        captured_messages: list[BaseMessage] = []

        async def mock_astream(messages: list[BaseMessage]):
            captured_messages.extend(messages)
            chunk = MagicMock()
            chunk.content = "Report with limitations."
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        orch = DeepResearchOrchestrator(
            llm=llm,
            config=DeepResearchConfig(enable_clarification=False, max_cycles=1),
            parent_tools=[],
        )

        [e async for e in orch.run("Test query", message_id="msg-integrity")]

        assert len(captured_messages) > 0
        system_msgs = [m for m in captured_messages if isinstance(m, SystemMessage)]
        assert len(system_msgs) == 1
        system_content = system_msgs[0].content
        assert "Information Integrity Rules" in system_content
        assert "STRICTLY on the research findings" in system_content
        assert "[unverified from search]" in system_content
        assert "Limitations" in system_content
        assert "Information Gaps" in system_content

    @pytest.mark.asyncio
    async def test_chat_history_passed_to_run(self):
        """Verify chat_history is incorporated into the orchestrator run."""
        plan_response = AIMessage(content="plan")
        plan_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "finalize_report", "args": {}}],
        )

        llm = self._make_llm([finalize_response])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "Report"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        chat_history = [
            HumanMessage(content="Previous question"),
            AIMessage(content="Previous answer"),
        ]

        orch = DeepResearchOrchestrator(
            llm=llm, config=DeepResearchConfig(enable_clarification=False, max_cycles=1)
        )

        events = [
            e async for e in orch.run("Follow up question", chat_history=chat_history)
        ]
        assert any(e.get("type") == "message" for e in events)
        assert orch.result.report == "Report"

    @pytest.mark.asyncio
    async def test_dispatch_forwards_sources_events(self):
        """Sub-agent SOURCES events are deduplicated and forwarded via event_queue."""
        import asyncio

        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm, parent_tools=[])
        orch._start_time = 1.0

        mock_agent = MagicMock()

        async def mock_run(query, chat_history, context, cancel_token):
            yield {
                "type": AgentEventType.SOURCES.value,
                "data": [
                    {"url": "https://example.com/a", "title": "Source A"},
                    {"url": "https://example.com/b", "title": "Source B"},
                ],
                "messageId": "child-msg",
            }
            yield {
                "type": AgentEventType.MESSAGE.value,
                "data": "Finding with sources.",
            }
            yield {
                "type": AgentEventType.MESSAGE_END.value,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

        mock_agent.run = mock_run

        with (
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.build_standalone_agent",
                return_value=mock_agent,
            ),
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.filter_tools",
                return_value=[],
            ),
        ):
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            results = await orch._dispatch_research_agents(
                tasks=[{"task": "Research with sources", "tc_id": "tc1"}],
                message_id="msg-parent",
                event_queue=queue,
            )

        assert "Finding with sources." in results[0]

        events: list[dict[str, object]] = []
        while not queue.empty():
            events.append(queue.get_nowait())

        source_events = [e for e in events if e.get("type") == "sources"]
        assert len(source_events) == 1
        assert source_events[0]["messageId"] == "msg-parent"
        assert len(source_events[0]["data"]) == 2
        assert source_events[0]["data"][0]["index"] == 1
        assert source_events[0]["data"][1]["index"] == 2

    @pytest.mark.asyncio
    async def test_on_report_ready_called_on_success(self):
        """on_report_ready callback is invoked when report is generated successfully."""
        plan_response = AIMessage(content="1. Plan")
        plan_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "finalize_report", "args": {}}],
        )

        llm = self._make_llm([finalize_response])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "Final report content"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        callback_result: list[DeepResearchResult] = []

        async def on_report_ready(result: DeepResearchResult) -> None:
            callback_result.append(result)

        orch = DeepResearchOrchestrator(
            llm=llm,
            config=DeepResearchConfig(enable_clarification=False, max_cycles=1),
            on_report_ready=on_report_ready,
        )

        _ = [e async for e in orch.run("test query")]
        assert len(callback_result) == 1
        assert callback_result[0].report == "Final report content"

    @pytest.mark.asyncio
    async def test_on_report_ready_not_called_on_error(self):
        """on_report_ready callback is NOT invoked when orchestrator errors."""
        llm = MagicMock()
        llm.model_name = "gpt-4o"
        llm.n_ctx = 10_000  # Too small → triggers ContextTooSmall error

        callback_called = False

        async def on_report_ready(result: DeepResearchResult) -> None:
            nonlocal callback_called
            callback_called = True

        orch = DeepResearchOrchestrator(llm=llm, on_report_ready=on_report_ready)
        _ = [e async for e in orch.run("query")]
        assert callback_called is False

    @pytest.mark.asyncio
    async def test_on_report_ready_failure_does_not_affect_result(self):
        """on_report_ready callback failure does not alter the research result."""
        plan_response = AIMessage(content="1. Plan")
        plan_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "finalize_report", "args": {}}],
        )

        llm = self._make_llm([finalize_response])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "Good report"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        async def on_report_ready(result: DeepResearchResult) -> None:
            raise RuntimeError("Callback exploded")

        orch = DeepResearchOrchestrator(
            llm=llm,
            config=DeepResearchConfig(enable_clarification=False, max_cycles=1),
            on_report_ready=on_report_ready,
        )

        _ = [e async for e in orch.run("test query")]
        assert orch.result.report == "Good report"
        assert orch.result.error is None

    @pytest.mark.asyncio
    async def test_on_report_ready_not_called_when_none(self):
        """No error when on_report_ready is None (default)."""
        plan_response = AIMessage(content="1. Plan")
        plan_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        finalize_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "finalize_report", "args": {}}],
        )

        llm = self._make_llm([finalize_response])
        llm.ainvoke = AsyncMock(return_value=plan_response)

        async def mock_astream(messages: list[BaseMessage]):
            chunk = MagicMock()
            chunk.content = "Report"
            chunk.usage_metadata = None
            yield chunk

        llm.astream = mock_astream

        orch = DeepResearchOrchestrator(
            llm=llm,
            config=DeepResearchConfig(enable_clarification=False, max_cycles=1),
        )

        events = [e async for e in orch.run("test query")]
        assert orch.result.report == "Report"
        assert any(e.get("type") == "message_end" for e in events)

    @pytest.mark.asyncio
    async def test_dispatch_deduplicates_sources_across_agents(self):
        """Same URL from different sub-agents should be deduplicated."""
        import asyncio

        llm = MagicMock()
        llm.model_name = "gpt-4o"
        orch = DeepResearchOrchestrator(llm=llm, parent_tools=[])
        orch._start_time = 1.0

        def make_mock_agent(sources: list[dict[str, str]]):
            agent = MagicMock()

            async def mock_run(query, chat_history, context, cancel_token):
                yield {
                    "type": AgentEventType.SOURCES.value,
                    "data": sources,
                    "messageId": "child",
                }
                yield {"type": AgentEventType.MESSAGE.value, "data": "Result."}
                yield {
                    "type": AgentEventType.MESSAGE_END.value,
                    "usage": {"input_tokens": 5, "output_tokens": 3},
                }

            agent.run = mock_run
            return agent

        agents = [
            make_mock_agent(
                [
                    {"url": "https://shared.com", "title": "Shared"},
                    {"url": "https://a.com", "title": "A"},
                ]
            ),
            make_mock_agent(
                [
                    {"url": "https://shared.com", "title": "Shared"},
                    {"url": "https://b.com", "title": "B"},
                ]
            ),
        ]
        call_count = 0

        def mock_build(**kwargs):
            nonlocal call_count
            agent = agents[call_count]
            call_count += 1
            return agent

        with (
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.build_standalone_agent",
                side_effect=mock_build,
            ),
            patch(
                "myrm_agent_harness.agent.sub_agents.builder.filter_tools",
                return_value=[],
            ),
        ):
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            await orch._dispatch_research_agents(
                tasks=[
                    {"task": "Task A", "tc_id": "tc1"},
                    {"task": "Task B", "tc_id": "tc2"},
                ],
                message_id="msg-parent",
                event_queue=queue,
            )

        events: list[dict[str, object]] = []
        while not queue.empty():
            events.append(queue.get_nowait())

        source_events = [e for e in events if e.get("type") == "sources"]
        all_sources = []
        for se in source_events:
            all_sources.extend(se["data"])

        urls = [s["url"] for s in all_sources]
        assert len(urls) == 3, f"Expected 3 unique sources, got {len(urls)}: {urls}"
        assert "https://shared.com" in urls
        assert "https://a.com" in urls
        assert "https://b.com" in urls
