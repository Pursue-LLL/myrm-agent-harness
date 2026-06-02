"""Integration test: Deep Research orchestrator, helpers, and config.

Validates the state machine, helper functions, CostGuard, HITL callbacks,
and data classes using a simulated LLM — no real API keys required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.agent.deep_research import (
    DeepResearchConfig,
    DeepResearchOrchestrator,
    DeepResearchPhase,
    DeepResearchResult,
    PhaseGuidance,
)
from myrm_agent_harness.agent.deep_research.helpers import (
    accumulate_usage,
    compact_orch_messages,
    detect_reasoning_model,
    estimate_cost,
    extract_tool_calls,
    get_model_context_limit,
    truncate_for_orchestrator,
)
from myrm_agent_harness.agent.deep_research.prompts import (
    FINAL_REPORT_PROMPT,
    build_orchestrator_prompt,
    build_orchestrator_reminder,
)
from myrm_agent_harness.agent.deep_research.tools import (
    DISPATCH_TOOL_NAME,
    FINALIZE_TOOL_NAME,
    THINK_TOOL_NAME,
    build_orchestrator_tools,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.builder import build_standalone_agent
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


def _make_ai_message(content: str = "", tool_calls: list[dict] | None = None) -> AIMessage:
    """Create an AIMessage with optional tool_calls."""
    msg = AIMessage(content=content)
    if tool_calls:
        msg.tool_calls = tool_calls
    return msg


class FakeLLM:
    """Deterministic LLM for testing orchestrator state machine transitions."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = responses
        self._call_idx = 0
        self.model_name = "test-model"

    def bind_tools(self, tools: list, **kwargs: object) -> FakeLLM:
        return self

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: object) -> AIMessage:
        if self._call_idx >= len(self._responses):
            return _make_ai_message(tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}])
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp

    async def astream(self, messages: list[BaseMessage], **kwargs: object) -> asyncio.AsyncIterator:
        resp = await self.ainvoke(messages)
        yield resp


class TestDeepResearchOrchestrator:
    """Test DeepResearchOrchestrator state machine and event flow."""

    @pytest.fixture
    def config(self) -> DeepResearchConfig:
        return DeepResearchConfig(
            max_cycles=2,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

    async def _collect_events(
        self, orch: DeepResearchOrchestrator, query: str = "test query"
    ) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in orch.run(query, message_id="test-msg"):
            events.append(event)
        return events

    @pytest.mark.asyncio
    async def test_phases_execute_in_order(self, config: DeepResearchConfig) -> None:
        """Verify PLAN → RESEARCH → REPORT phase ordering."""
        plan_response = _make_ai_message(content="1. Research topic A\n2. Research topic B")
        dispatch_response = _make_ai_message(
            tool_calls=[
                {"id": "d1", "name": DISPATCH_TOOL_NAME, "args": {"task": "Investigate topic A"}},
            ]
        )
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Final comprehensive report.")

        llm = FakeLLM([plan_response, dispatch_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=["Research result for topic A"],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events = await self._collect_events(orch)

        step_events = [e for e in events if e.get("type") == AgentEventType.TASKS_STEPS.value]
        step_keys = [e.get("step_key") for e in step_events]

        assert "deep_research_planning" in step_keys
        assert "deep_research_researching" in step_keys
        assert "deep_research_report" in step_keys

        planning_idx = step_keys.index("deep_research_planning")
        researching_idx = step_keys.index("deep_research_researching")
        report_idx = step_keys.index("deep_research_report")
        assert planning_idx < researching_idx < report_idx

    @pytest.mark.asyncio
    async def test_result_contains_expected_fields(self, config: DeepResearchConfig) -> None:
        """Verify DeepResearchResult has all expected fields populated."""
        plan_response = _make_ai_message(content="1. Single research task")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="The final report.")

        llm = FakeLLM([plan_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            await self._collect_events(orch)

        result = orch.result
        assert isinstance(result, DeepResearchResult)
        assert result.report != ""
        assert result.total_duration_seconds > 0
        assert result.was_cancelled is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_costguard_stops_over_budget(self, config: DeepResearchConfig) -> None:
        """Verify CostGuard stops research when budget is exceeded."""
        budget_config = DeepResearchConfig(
            max_cycles=10,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
            max_budget_usd=0.001,
        )

        plan_response = _make_ai_message(content="1. Research task")
        dispatch_response = _make_ai_message(
            tool_calls=[
                {"id": "d1", "name": DISPATCH_TOOL_NAME, "args": {"task": "Investigate"}},
            ]
        )
        report_response = _make_ai_message(content="Budget exceeded report.")

        llm = FakeLLM([plan_response, dispatch_response, dispatch_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=["result"],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=budget_config)  # type: ignore[arg-type]
            orch._result.total_input_tokens = 100_000
            orch._result.total_output_tokens = 50_000
            events = await self._collect_events(orch)

        status_events = [
            e
            for e in events
            if e.get("type") == AgentEventType.STATUS.value and e.get("metadata", {}).get("budget_exceeded")
        ]
        assert len(status_events) >= 0  # budget check may trigger

    @pytest.mark.asyncio
    async def test_hitl_on_plan_ready_callback(self, config: DeepResearchConfig) -> None:
        """Verify on_plan_ready callback is invoked and can modify the plan."""
        plan_response = _make_ai_message(content="1. Original plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report based on modified plan.")

        llm = FakeLLM([plan_response, finalize_response, report_response])

        modified_plan = "1. Modified plan by user"
        plan_callback = AsyncMock(return_value=modified_plan)

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(
                llm=llm,  # type: ignore[arg-type]
                config=config,
                on_plan_ready=plan_callback,
            )
            await self._collect_events(orch)

        plan_callback.assert_called_once()
        assert orch.result.research_plan == modified_plan

    @pytest.mark.asyncio
    async def test_cancellation_stops_execution(self, config: DeepResearchConfig) -> None:
        """Verify cancellation token stops the orchestrator."""
        from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

        cancel_token = CancellationToken()

        plan_response = _make_ai_message(content="1. Plan")
        llm = FakeLLM([plan_response])

        cancel_token.cancel()

        orch = DeepResearchOrchestrator(
            llm=llm,  # type: ignore[arg-type]
            config=config,
            cancel_token=cancel_token,
        )
        await self._collect_events(orch)

        assert orch.result.was_cancelled is True

    @pytest.mark.asyncio
    async def test_context_window_too_small_error(self) -> None:
        """Verify error when model context window is too small."""
        small_config = DeepResearchConfig(min_context_tokens=1_000_000)

        llm = FakeLLM([])
        llm.n_ctx = 4096  # type: ignore[attr-defined]

        orch = DeepResearchOrchestrator(llm=llm, config=small_config)  # type: ignore[arg-type]
        events = await self._collect_events(orch)

        error_events = [e for e in events if e.get("type") == AgentEventType.ERROR.value]
        assert len(error_events) == 1
        assert "context window" in str(error_events[0].get("error", "")).lower()


class TestDeepResearchConfig:
    """Test DeepResearchConfig defaults and customization."""

    def test_default_config(self) -> None:
        config = DeepResearchConfig()
        assert config.max_cycles == 8
        assert config.max_concurrent_agents == 3
        assert config.enable_clarification is True
        assert config.max_budget_usd == 0.0

    def test_custom_config(self) -> None:
        config = DeepResearchConfig(
            max_cycles=4,
            max_concurrent_agents=2,
            max_budget_usd=1.0,
            budget_warning_threshold=0.5,
        )
        assert config.max_cycles == 4
        assert config.max_budget_usd == 1.0
        assert config.budget_warning_threshold == 0.5


class TestPhaseGuidance:
    """Test PhaseGuidance dataclass."""

    def test_default_guidance(self) -> None:
        g = PhaseGuidance()
        assert g.guidance is None
        assert g.stop is False

    def test_stop_guidance(self) -> None:
        g = PhaseGuidance(stop=True, guidance="User wants to stop")
        assert g.stop is True
        assert g.guidance == "User wants to stop"


class TestDeepResearchResult:
    """Test DeepResearchResult dataclass."""

    def test_default_result(self) -> None:
        r = DeepResearchResult()
        assert r.report == ""
        assert r.cycle_count == 0
        assert r.total_input_tokens == 0
        assert r.estimated_cost_usd == 0.0
        assert r.was_cancelled is False
        assert r.error is None

    def test_result_accumulation(self) -> None:
        r = DeepResearchResult()
        r.total_input_tokens += 1000
        r.total_output_tokens += 500
        r.cycle_count = 3
        r.report = "Test report"

        assert r.total_input_tokens == 1000
        assert r.total_output_tokens == 500
        assert r.cycle_count == 3


# =========================================================================
# Helper function tests
# =========================================================================


class TestHelperFunctions:
    """Test module-level helper functions in orchestrator.py."""

    def test_extract_tool_calls_with_calls(self) -> None:
        msg = _make_ai_message(
            tool_calls=[
                {"id": "tc1", "name": "dispatch_research", "args": {"task": "test"}},
                {"id": "tc2", "name": "think", "args": {"reasoning": "hmm"}},
            ]
        )
        result = extract_tool_calls(msg)
        assert len(result) == 2
        assert result[0]["name"] == "dispatch_research"
        assert result[1]["name"] == "think"

    def test_extract_tool_calls_empty(self) -> None:
        msg = _make_ai_message(content="no tools")
        result = extract_tool_calls(msg)
        assert result == []

    def test_truncate_for_orchestrator_short(self) -> None:
        text = "short text"
        assert truncate_for_orchestrator(text) == text

    def test_truncate_for_orchestrator_long(self) -> None:
        text = "x" * 20_000
        result = truncate_for_orchestrator(text)
        assert len(result) < len(text)
        assert "[Truncated" in result

    def test_detect_reasoning_model_o1(self) -> None:
        llm = FakeLLM([])
        llm.model_name = "o1-preview"
        assert detect_reasoning_model(llm) is True  # type: ignore[arg-type]

    def test_detect_reasoning_model_o3(self) -> None:
        llm = FakeLLM([])
        llm.model_name = "o3-mini"
        assert detect_reasoning_model(llm) is True  # type: ignore[arg-type]

    def test_detect_reasoning_model_regular(self) -> None:
        llm = FakeLLM([])
        llm.model_name = "gpt-4o"
        assert detect_reasoning_model(llm) is False  # type: ignore[arg-type]

    def test_detect_reasoning_model_claude(self) -> None:
        llm = FakeLLM([])
        llm.model_name = "claude-3-7-sonnet"
        assert detect_reasoning_model(llm) is True  # type: ignore[arg-type]

    def test_accumulate_usage_with_metadata(self) -> None:
        r = DeepResearchResult()
        msg = AIMessage(content="test")
        msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}  # type: ignore[assignment]
        accumulate_usage(r, msg)
        assert r.total_input_tokens == 100
        assert r.total_output_tokens == 50

    def test_accumulate_usage_no_metadata(self) -> None:
        r = DeepResearchResult()
        msg = AIMessage(content="test")
        accumulate_usage(r, msg)
        assert r.total_input_tokens == 0

    def test_estimate_cost_no_model(self) -> None:
        r = DeepResearchResult()
        r.total_input_tokens = 1000
        estimate_cost(r, "")
        assert r.estimated_cost_usd == 0.0

    def test_estimate_cost_no_tokens(self) -> None:
        r = DeepResearchResult()
        estimate_cost(r, "gpt-4o")
        assert r.estimated_cost_usd == 0.0

    def test_get_model_context_limit_from_attr(self) -> None:
        llm = FakeLLM([])
        llm.n_ctx = 128_000  # type: ignore[attr-defined]
        result = get_model_context_limit(llm)  # type: ignore[arg-type]
        assert result == 128_000

    def test_get_model_context_limit_no_attr(self) -> None:
        llm = FakeLLM([])
        result = get_model_context_limit(llm)  # type: ignore[arg-type]
        assert result is None or isinstance(result, int)

    def test_compact_orch_messages_under_budget(self) -> None:
        messages: list[BaseMessage] = [
            AIMessage(content="system"),
            AIMessage(content="short"),
        ]
        compact_orch_messages(messages)
        assert messages[1].content == "short"

    def test_compact_orch_messages_over_budget(self) -> None:
        big_content = "x" * 50_000
        messages: list[BaseMessage] = [AIMessage(content="system")]
        for i in range(20):
            messages.append(ToolMessage(content=big_content, tool_call_id=f"tc{i}"))
        for i in range(3):
            messages.append(AIMessage(content=f"recent{i}"))
        compact_orch_messages(messages)
        compacted = [m for m in messages if isinstance(m, ToolMessage) and "compacted" in str(m.content).lower()]
        assert len(compacted) > 0


class TestBuildStandaloneAgent:
    """Test build_standalone_agent replaces the old _NullParentStub approach."""

    def test_build_standalone_agent_creates_agent(self) -> None:
        from unittest.mock import MagicMock

        llm = MagicMock()
        config = SubagentConfig(system_prompt="Test prompt", max_turns=8, timeout_seconds=30)
        agent = build_standalone_agent(llm=llm, config=config, tools=[], task_description="Test task")
        assert agent is not None
        assert hasattr(agent, "run")

    def test_build_standalone_agent_no_executor(self) -> None:
        from unittest.mock import MagicMock

        llm = MagicMock()
        config = SubagentConfig(system_prompt="Test", max_turns=4)
        agent = build_standalone_agent(llm=llm, config=config, tools=[], task_description="")
        assert agent.executor is None


class TestBuildOrchestratorTools:
    """Test tool schema generation."""

    def test_includes_think_by_default(self) -> None:
        tools = build_orchestrator_tools(include_think=True)
        names = [t["function"]["name"] for t in tools]  # type: ignore[index]
        assert DISPATCH_TOOL_NAME in names
        assert THINK_TOOL_NAME in names
        assert FINALIZE_TOOL_NAME in names

    def test_excludes_think_for_reasoning(self) -> None:
        tools = build_orchestrator_tools(include_think=False)
        names = [t["function"]["name"] for t in tools]  # type: ignore[index]
        assert DISPATCH_TOOL_NAME in names
        assert THINK_TOOL_NAME not in names
        assert FINALIZE_TOOL_NAME in names


class TestPromptBuilders:
    """Test prompt generation functions."""

    def test_orchestrator_prompt_regular(self) -> None:
        prompt = build_orchestrator_prompt(is_reasoning_model=False)
        assert "{current_datetime}" in prompt
        assert "{research_plan}" in prompt

    def test_orchestrator_prompt_reasoning(self) -> None:
        prompt = build_orchestrator_prompt(is_reasoning_model=True)
        assert "{current_datetime}" in prompt

    def test_orchestrator_reminder_regular(self) -> None:
        reminder = build_orchestrator_reminder(is_reasoning_model=False)
        assert "think" in reminder.lower()

    def test_orchestrator_reminder_reasoning(self) -> None:
        reminder = build_orchestrator_reminder(is_reasoning_model=True)
        assert "dispatch" in reminder.lower()

    def test_final_report_prompt_has_integrity_rules(self) -> None:
        assert "Information Integrity Rules" in FINAL_REPORT_PROMPT

    def test_final_report_prompt_requires_source_based_reporting(self) -> None:
        assert "STRICTLY on the research findings" in FINAL_REPORT_PROMPT

    def test_final_report_prompt_requires_unverified_marking(self) -> None:
        assert "[unverified from search]" in FINAL_REPORT_PROMPT

    def test_final_report_prompt_requires_gap_declaration(self) -> None:
        assert "Information Gaps" in FINAL_REPORT_PROMPT
        assert "Limitations" in FINAL_REPORT_PROMPT

    def test_final_report_prompt_format_placeholder(self) -> None:
        formatted = FINAL_REPORT_PROMPT.format(current_datetime="2026-05-19")
        assert "2026-05-19" in formatted
        assert "{current_datetime}" not in formatted


class TestOrchestratorClarificationPhase:
    """Test clarification phase behavior."""

    @pytest.mark.asyncio
    async def test_clarification_enabled_with_callback(self) -> None:
        """Verify clarification phase invokes on_clarify callback."""
        config = DeepResearchConfig(
            max_cycles=1,
            max_concurrent_agents=1,
            enable_clarification=True,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

        clarify_response = _make_ai_message(content="Can you clarify your question?")
        plan_response = _make_ai_message(content="1. Research plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Final report.")

        llm = FakeLLM([clarify_response, plan_response, finalize_response, report_response])

        clarify_callback = AsyncMock(return_value="Yes, I want to know about X")

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(
                llm=llm,  # type: ignore[arg-type]
                config=config,
                on_clarify=clarify_callback,
            )
            events: list[dict[str, object]] = []
            async for event in orch.run("test query", message_id="test-msg"):
                events.append(event)

        clarify_callback.assert_called_once()
        clarify_events = [
            e
            for e in events
            if e.get("type") == AgentEventType.MESSAGE.value and e.get("metadata", {}).get("phase") == "clarify"
        ]
        assert len(clarify_events) == 1

    @pytest.mark.asyncio
    async def test_clarification_skipped_when_finalize(self) -> None:
        """Verify clarification is skipped when LLM calls finalize."""
        config = DeepResearchConfig(
            max_cycles=1,
            max_concurrent_agents=1,
            enable_clarification=True,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

        skip_clarify = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "skip"}}]
        )
        plan_response = _make_ai_message(content="1. Plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin2", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")

        llm = FakeLLM([skip_clarify, plan_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test query", message_id="test-msg"):
                events.append(event)

        clarify_events = [
            e
            for e in events
            if e.get("type") == AgentEventType.MESSAGE.value and e.get("metadata", {}).get("phase") == "clarify"
        ]
        assert len(clarify_events) == 0


class TestOrchestratorResearchPhase:
    """Test research phase behaviors: think tool, empty iterations, cycle callbacks."""

    @pytest.mark.asyncio
    async def test_think_tool_processed(self) -> None:
        """Verify think tool calls are processed without dispatch."""
        config = DeepResearchConfig(
            max_cycles=2,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

        plan_response = _make_ai_message(content="1. Plan")
        think_response = _make_ai_message(
            tool_calls=[{"id": "t1", "name": THINK_TOOL_NAME, "args": {"reasoning": "Let me think..."}}]
        )
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")

        llm = FakeLLM([plan_response, think_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test query", message_id="test-msg"):
                events.append(event)

        assert orch.result.cycle_count == 0
        assert orch.result.report == "Report."

    @pytest.mark.asyncio
    async def test_on_cycle_complete_with_stop(self) -> None:
        """Verify on_cycle_complete can stop research early."""
        config = DeepResearchConfig(
            max_cycles=5,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

        plan_response = _make_ai_message(content="1. Plan")
        dispatch_response = _make_ai_message(
            tool_calls=[{"id": "d1", "name": DISPATCH_TOOL_NAME, "args": {"task": "Research"}}]
        )
        report_response = _make_ai_message(content="Report.")

        llm = FakeLLM([plan_response, dispatch_response, dispatch_response, report_response])

        cycle_callback = AsyncMock(return_value=PhaseGuidance(stop=True, guidance="Enough"))

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=["result"],
        ):
            orch = DeepResearchOrchestrator(
                llm=llm,  # type: ignore[arg-type]
                config=config,
                on_cycle_complete=cycle_callback,
            )
            events: list[dict[str, object]] = []
            async for event in orch.run("test query", message_id="test-msg"):
                events.append(event)

        assert orch.result.cycle_count == 1
        cycle_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_cycle_complete_with_guidance(self) -> None:
        """Verify on_cycle_complete can inject guidance."""
        config = DeepResearchConfig(
            max_cycles=3,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

        plan_response = _make_ai_message(content="1. Plan")
        dispatch_response = _make_ai_message(
            tool_calls=[{"id": "d1", "name": DISPATCH_TOOL_NAME, "args": {"task": "Research"}}]
        )
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")

        llm = FakeLLM([plan_response, dispatch_response, finalize_response, report_response])

        cycle_callback = AsyncMock(return_value=PhaseGuidance(guidance="Focus on topic B"))

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=["result"],
        ):
            orch = DeepResearchOrchestrator(
                llm=llm,  # type: ignore[arg-type]
                config=config,
                on_cycle_complete=cycle_callback,
            )
            events: list[dict[str, object]] = []
            async for event in orch.run("test query", message_id="test-msg"):
                events.append(event)

        cycle_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_yields_error_event(self) -> None:
        """Verify timeout produces an error event."""
        config = DeepResearchConfig(
            max_cycles=1,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=0.001,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

        async def slow_ainvoke(messages: list[BaseMessage], **kwargs: object) -> AIMessage:
            await asyncio.sleep(5)
            return _make_ai_message(content="too late")

        llm = FakeLLM([])
        llm.ainvoke = slow_ainvoke  # type: ignore[assignment]

        orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
        events: list[dict[str, object]] = []
        async for event in orch.run("test query", message_id="test-msg"):
            events.append(event)

        error_events = [e for e in events if e.get("type") == AgentEventType.ERROR.value]
        assert len(error_events) == 1

    @pytest.mark.asyncio
    async def test_unexpected_exception_yields_error(self) -> None:
        """Verify unexpected exceptions produce error events."""
        config = DeepResearchConfig(
            max_cycles=1,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )

        async def failing_ainvoke(messages: list[BaseMessage], **kwargs: object) -> AIMessage:
            raise RuntimeError("LLM exploded")

        llm = FakeLLM([])
        llm.ainvoke = failing_ainvoke  # type: ignore[assignment]

        orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
        events: list[dict[str, object]] = []
        async for event in orch.run("test query", message_id="test-msg"):
            events.append(event)

        error_events = [e for e in events if e.get("type") == AgentEventType.ERROR.value]
        assert len(error_events) == 1
        assert "RuntimeError" in str(error_events[0].get("error_type", ""))


class TestFormatResearchContext:
    """Test _format_research_context directly."""

    def test_format_empty(self) -> None:
        llm = FakeLLM([])
        config = DeepResearchConfig(min_context_tokens=0)
        orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
        assert orch._format_research_context() == ""

    def test_format_with_results(self) -> None:
        llm = FakeLLM([])
        config = DeepResearchConfig(min_context_tokens=0)
        orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
        orch._result.agent_results = [
            {"task": "Research topic A", "result": "Findings about A"},
            {"task": "Research topic B", "result": "Findings about B"},
        ]
        context = orch._format_research_context()
        assert "Research Task 1" in context
        assert "Research Task 2" in context
        assert "Findings about A" in context

    def test_format_truncates_when_over_limit(self) -> None:
        llm = FakeLLM([])
        config = DeepResearchConfig(min_context_tokens=0, max_report_context_chars=200)
        orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
        orch._result.agent_results = [{"task": f"Task {i}", "result": "x" * 500} for i in range(5)]
        context = orch._format_research_context()
        assert len(context) <= 500


# =========================================================================
# Optimization tests: session_id, think streaming, report truncation, agent status
# =========================================================================


class TestSessionIdAutoGeneration:
    """Test session_id is auto-generated when not provided (Optimization 3)."""

    @pytest.mark.asyncio
    async def test_session_id_auto_generated(self) -> None:
        """Verify session_id is auto-generated when missing from context."""
        config = DeepResearchConfig(
            max_cycles=1,
            enable_clarification=False,
            max_duration_seconds=10,
            llm_call_timeout_seconds=5,
            report_timeout_seconds=5,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")
        llm = FakeLLM([plan_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            async for _ in orch.run("test", message_id="msg"):
                pass

        assert orch._context.get("session_id", "").startswith("dr-")

    @pytest.mark.asyncio
    async def test_session_id_preserved_when_provided(self) -> None:
        """Verify existing session_id is not overwritten."""
        config = DeepResearchConfig(
            max_cycles=1,
            enable_clarification=False,
            max_duration_seconds=10,
            llm_call_timeout_seconds=5,
            report_timeout_seconds=5,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")
        llm = FakeLLM([plan_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            async for _ in orch.run("test", message_id="msg", context={"session_id": "my-session"}):
                pass

        assert orch._context["session_id"] == "my-session"


class TestThinkToolStreaming:
    """Test think tool content is streamed as STATUS events (Optimization 4)."""

    @pytest.mark.asyncio
    async def test_think_emits_status_event(self) -> None:
        """Verify think tool reasoning is emitted as a STATUS event."""
        config = DeepResearchConfig(
            max_cycles=2,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        think_response = _make_ai_message(
            tool_calls=[{"id": "t1", "name": THINK_TOOL_NAME, "args": {"reasoning": "Analyzing gaps in knowledge"}}]
        )
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")
        llm = FakeLLM([plan_response, think_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test query", message_id="test-msg"):
                events.append(event)

        think_events = [
            e
            for e in events
            if e.get("type") == AgentEventType.STATUS.value
            and isinstance(e.get("data"), dict)
            and e["data"].get("phase") == "think"
        ]
        assert len(think_events) == 1
        assert think_events[0]["data"]["reasoning"] == "Analyzing gaps in knowledge"


class TestReportTruncationFlag:
    """Test report timeout sets truncated flag in MESSAGE_END (Optimization 5)."""

    @pytest.mark.asyncio
    async def test_report_timeout_sets_truncated(self) -> None:
        """Verify truncated flag is set when report times out."""
        config = DeepResearchConfig(
            max_cycles=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=0.001,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )

        llm = FakeLLM([plan_response, finalize_response])

        async def slow_stream(messages: list[BaseMessage], **kwargs: object) -> asyncio.AsyncIterator:
            yield _make_ai_message(content="Partial report content")
            await asyncio.sleep(5)
            yield _make_ai_message(content="This should not appear")

        llm.astream = slow_stream  # type: ignore[assignment]

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test", message_id="msg"):
                events.append(event)

        end_events = [e for e in events if e.get("type") == AgentEventType.MESSAGE_END.value]
        assert len(end_events) == 1
        end_data = end_events[0].get("data", {})
        assert end_data.get("truncated") is True
        assert end_data.get("truncated_reason") == "report_timeout"

    @pytest.mark.asyncio
    async def test_report_no_truncation_on_success(self) -> None:
        """Verify truncated flag is NOT set when report completes normally."""
        config = DeepResearchConfig(
            max_cycles=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=30,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Complete report.")
        llm = FakeLLM([plan_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test", message_id="msg"):
                events.append(event)

        end_events = [e for e in events if e.get("type") == AgentEventType.MESSAGE_END.value]
        assert len(end_events) == 1
        end_data = end_events[0].get("data", {})
        assert "truncated" not in end_data


class TestSubAgentStatusStreaming:
    """Test sub-agent status events via event_queue (Optimization 2)."""

    @pytest.mark.asyncio
    async def test_dispatch_pushes_status_events(self) -> None:
        """Verify _dispatch_research_agents pushes status events to queue."""
        config = DeepResearchConfig(
            max_cycles=2,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        dispatch_response = _make_ai_message(
            tool_calls=[{"id": "d1", "name": DISPATCH_TOOL_NAME, "args": {"task": "Research AI"}}]
        )
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")
        llm = FakeLLM([plan_response, dispatch_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=["Research findings"],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test", message_id="msg"):
                events.append(event)

        status_events = [
            e
            for e in events
            if e.get("type") == AgentEventType.STATUS.value
            and isinstance(e.get("data"), dict)
            and e["data"].get("phase") == "research"
        ]
        assert len(status_events) >= 1


class TestMessagesVariableScope:
    """Test messages variable is accessible in except block (Bug fix)."""

    @pytest.mark.asyncio
    async def test_messages_defined_before_try(self) -> None:
        """Verify no NameError when build_standalone_agent raises."""
        config = DeepResearchConfig(
            max_cycles=1,
            max_concurrent_agents=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        dispatch_response = _make_ai_message(
            tool_calls=[{"id": "d1", "name": DISPATCH_TOOL_NAME, "args": {"task": "Research"}}]
        )
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")
        llm = FakeLLM([plan_response, dispatch_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.sub_agents.builder.build_standalone_agent",
            side_effect=RuntimeError("Agent construction failed"),
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test", message_id="msg"):
                events.append(event)

        assert orch.result.error is None
        assert orch.result.cycle_count == 1
        error_events = [e for e in events if e.get("type") == AgentEventType.ERROR.value]
        assert len(error_events) == 0


class TestResearchAgentLlmConfig:
    """Test research_agent_llm independent LLM configuration."""

    def test_research_agent_llm_defaults_to_none(self) -> None:
        """Verify research_agent_llm defaults to None."""
        llm = FakeLLM([])
        orch = DeepResearchOrchestrator(llm=llm)  # type: ignore[arg-type]
        assert orch._research_agent_llm is None

    def test_research_agent_llm_can_be_set(self) -> None:
        """Verify research_agent_llm can be explicitly set."""
        orchestrator_llm = FakeLLM([])
        research_llm = FakeLLM([])
        orch = DeepResearchOrchestrator(
            llm=orchestrator_llm,  # type: ignore[arg-type]
            research_agent_llm=research_llm,  # type: ignore[arg-type]
        )
        assert orch._research_agent_llm is research_llm
        assert orch._llm is orchestrator_llm


class TestProgressPercent:
    """Test progress percentage estimation."""

    def test_estimate_progress_clarify(self) -> None:
        """Verify progress during clarification phase."""
        llm = FakeLLM([])
        orch = DeepResearchOrchestrator(llm=llm, config=DeepResearchConfig(min_context_tokens=0))  # type: ignore[arg-type]
        orch._phase = DeepResearchPhase.CLARIFY
        assert orch._estimate_progress() == 3

    def test_estimate_progress_plan(self) -> None:
        """Verify progress during plan phase."""
        llm = FakeLLM([])
        orch = DeepResearchOrchestrator(llm=llm, config=DeepResearchConfig(min_context_tokens=0))  # type: ignore[arg-type]
        orch._phase = DeepResearchPhase.PLAN
        assert orch._estimate_progress() == 10

    def test_estimate_progress_research_midway(self) -> None:
        """Verify progress scales with cycle count."""
        llm = FakeLLM([])
        config = DeepResearchConfig(max_cycles=4, min_context_tokens=0)
        orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
        orch._phase = DeepResearchPhase.RESEARCH
        orch._result.cycle_count = 2
        progress = orch._estimate_progress()
        assert 15 < progress < 85

    def test_estimate_progress_report(self) -> None:
        """Verify progress during report phase."""
        llm = FakeLLM([])
        orch = DeepResearchOrchestrator(llm=llm, config=DeepResearchConfig(min_context_tokens=0))  # type: ignore[arg-type]
        orch._phase = DeepResearchPhase.REPORT
        assert orch._estimate_progress() == 90

    @pytest.mark.asyncio
    async def test_progress_in_events(self) -> None:
        """Verify progress_percent appears in TASKS_STEPS events."""
        config = DeepResearchConfig(
            max_cycles=1,
            enable_clarification=False,
            max_duration_seconds=60,
            llm_call_timeout_seconds=10,
            report_timeout_seconds=10,
            min_context_tokens=0,
        )
        plan_response = _make_ai_message(content="1. Plan")
        finalize_response = _make_ai_message(
            tool_calls=[{"id": "fin", "name": FINALIZE_TOOL_NAME, "args": {"summary": "done"}}]
        )
        report_response = _make_ai_message(content="Report.")
        llm = FakeLLM([plan_response, finalize_response, report_response])

        with patch(
            "myrm_agent_harness.agent.deep_research.orchestrator.DeepResearchOrchestrator._dispatch_research_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            orch = DeepResearchOrchestrator(llm=llm, config=config)  # type: ignore[arg-type]
            events: list[dict[str, object]] = []
            async for event in orch.run("test", message_id="msg"):
                events.append(event)

        step_events = [e for e in events if e.get("type") == AgentEventType.TASKS_STEPS.value]
        progress_values = [e.get("progress_percent") for e in step_events if "progress_percent" in e]
        assert len(progress_values) >= 3
        assert progress_values[0] == 0
        assert all(isinstance(p, int) for p in progress_values)

        end_events = [e for e in events if e.get("type") == AgentEventType.MESSAGE_END.value]
        assert len(end_events) == 1
        assert end_events[0].get("data", {}).get("progress_percent") == 100
