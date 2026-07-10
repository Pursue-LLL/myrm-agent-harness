"""Deep Research orchestrator — multi-phase state machine.

[INPUT]
- helpers (POS: DeepResearchResult, pure helper functions)
- config::DeepResearchConfig, DeepResearchPhase (POS: configuration & phase enum)
- prompts (POS: prompt templates for each phase)
- tools (POS: orchestrator meta-tool schemas & names)
- meta_tools.clarification::AskQuestionInput, QuestionItem (POS: structured user clarification forms)
- agent.types::AgentEventType (POS: event types)
- agent.sub_agents.builder::build_standalone_agent, filter_tools (POS: agent construction)
- utils.runtime.cancellation::CancellationToken (POS: cooperative cancellation)
- langchain_core (POS: BaseChatModel, messages)

[OUTPUT]
- DeepResearchOrchestrator: async generator that drives the research lifecycle
- DeepResearchResult: re-exported from helpers

[POS]
Multi-phase orchestrator for Deep Research:

  CLARIFY → PLAN → EXPLORE → RESEARCH (cycles) → REPORT

Each phase uses direct LLM calls (not a full LangGraph agent) for tighter
control over tool-call interception and state transitions. Research sub-agents
are launched via build_standalone_agent() for full tool isolation.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage

from myrm_agent_harness.agent.streaming.source_tracker import SourceTracker
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ._orchestrator_phases import DeepResearchPhasesMixin
from ._orchestrator_plan_research import DeepResearchPlanResearchMixin
from .config import DeepResearchConfig, DeepResearchPhase
from .helpers import (
    DeepResearchResult,
    detect_reasoning_model,
    estimate_cost,
    get_datetime_str,
    get_model_context_limit,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.meta_tools.clarification import AskQuestionInput
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

    from .config import PhaseGuidance

    ClarifyCallback = Callable[[AskQuestionInput], Awaitable[str | list[str] | dict[str, str | list[str]] | None]]
    PlanCallback = Callable[[str], Awaitable[str | None]]
    ExploreCallback = Callable[[str], Awaitable[str | None]]
    CycleCallback = Callable[[int, list[dict[str, str]]], Awaitable[PhaseGuidance | None]]
    ReportReadyCallback = Callable[["DeepResearchResult"], Awaitable[None]]

logger = get_agent_logger(__name__)


class DeepResearchOrchestrator(DeepResearchPlanResearchMixin, DeepResearchPhasesMixin):
    """State-machine orchestrator for Deep Research.

    Usage::

        orch = DeepResearchOrchestrator(llm, config, tools, cancel_token)
        async for event in orch.run(query, chat_history, message_id, context):
            yield event  # forward to client
    """

    def __init__(
        self,
        llm: BaseChatModel,
        config: DeepResearchConfig | None = None,
        parent_tools: list[BaseTool] | None = None,
        cancel_token: CancellationToken | None = None,
        context: dict[str, object] | None = None,
        executor: object | None = None,
        on_clarify: ClarifyCallback | None = None,
        on_plan_ready: PlanCallback | None = None,
        on_explore: ExploreCallback | None = None,
        on_cycle_complete: CycleCallback | None = None,
        on_report_ready: ReportReadyCallback | None = None,
        research_agent_llm: BaseChatModel | None = None,
    ) -> None:
        self._llm = llm
        self._research_agent_llm = research_agent_llm
        self._config = config or DeepResearchConfig()
        self._parent_tools = parent_tools or []
        self._cancel_token = cancel_token
        self._context = context or {}
        self._executor = executor
        self._on_clarify = on_clarify
        self._on_plan_ready = on_plan_ready
        self._on_explore = on_explore
        self._on_cycle_complete = on_cycle_complete
        self._on_report_ready = on_report_ready
        self._is_reasoning = detect_reasoning_model(llm)
        self._result = DeepResearchResult()
        self._source_tracker = SourceTracker()
        self._phase = DeepResearchPhase.CLARIFY
        self._start_time = 0.0
        self._budget_warning_sent = False

    def _is_cancelled(self) -> bool:
        return self._cancel_token is not None and self._cancel_token.is_cancelled

    def _is_timed_out(self) -> bool:
        return (time.time() - self._start_time) > self._config.max_duration_seconds

    def _update_cost_estimate(self) -> None:
        """Re-estimate cost using current accumulated token counts."""
        model_name = getattr(self._llm, "model_name", "") or getattr(self._llm, "model", "") or ""
        estimate_cost(self._result, model_name)

    def _is_over_budget(self) -> bool:
        """Check if accumulated cost exceeds the configured budget."""
        budget = self._config.max_budget_usd
        return budget > 0 and self._result.estimated_cost_usd >= budget

    def _is_budget_warning(self) -> bool:
        """Check if accumulated cost exceeds the warning threshold."""
        budget = self._config.max_budget_usd
        threshold = self._config.budget_warning_threshold
        return budget > 0 and self._result.estimated_cost_usd >= budget * threshold

    def _accumulate_child_usage(self, event: dict[str, object]) -> None:
        """Accumulate token usage from a child agent's MESSAGE_END event.

        Only accumulates raw token counts; cost is recalculated centrally
        by estimate_cost() to avoid double-counting.
        """
        usage = event.get("usage")
        if isinstance(usage, dict):
            self._result.total_input_tokens += int(usage.get("input_tokens", 0))
            self._result.total_output_tokens += int(usage.get("output_tokens", 0))

    def _make_event(self, event_type: AgentEventType, message_id: str, **kwargs: object) -> dict[str, object]:
        return {"type": event_type.value, "messageId": message_id, **kwargs}

    def _estimate_progress(self) -> int:
        """Estimate overall progress as a percentage (0-100).

        Phase weights: CLARIFY=3%, PLAN=7%, EXPLORE=5%, RESEARCH=70%, REPORT=15%.
        Within RESEARCH, progress scales linearly with cycle_count/max_cycles.
        """
        phase = self._phase
        if phase == DeepResearchPhase.CLARIFY:
            return 3
        if phase == DeepResearchPhase.PLAN:
            return 10
        if phase == DeepResearchPhase.EXPLORE:
            return 13
        if phase == DeepResearchPhase.RESEARCH:
            max_cycles = self._config.max_cycles_reasoning if self._is_reasoning else self._config.max_cycles
            cycle_progress = min(self._result.cycle_count / max(max_cycles, 1), 1.0)
            return 15 + int(cycle_progress * 70)
        return 90

    async def run(
        self,
        query: str,
        chat_history: list[BaseMessage] | None = None,
        message_id: str = "",
        context: dict[str, object] | None = None,
    ) -> AsyncGenerator[dict[str, object]]:
        """Drive the full deep research lifecycle, yielding streaming events."""
        self._start_time = time.time()
        self._context = context or self._context
        if not self._context.get("session_id"):
            self._context["session_id"] = f"dr-{uuid.uuid4().hex[:8]}"
        datetime_str = get_datetime_str()

        context_limit = get_model_context_limit(self._llm)
        if context_limit and context_limit < self._config.min_context_tokens:
            error_msg = (
                f"Model context window ({context_limit} tokens) is below the minimum "
                f"required for Deep Research ({self._config.min_context_tokens} tokens). "
                f"Please use a model with a larger context window."
            )
            logger.error("[deep-research] %s", error_msg)
            yield self._make_event(AgentEventType.ERROR, message_id, error=error_msg, error_type="ContextTooSmall")
            return

        yield self._make_event(
            AgentEventType.TASKS_STEPS,
            message_id,
            step_key="deep_research_root",
            is_plan=True,
            status="running",
            data=[{"text": "Deep Research"}],
            tool_name=None,
            progress_percent=0,
        )

        yield self._make_event(
            AgentEventType.TASKS_STEPS,
            message_id,
            step_key="deep_research_start",
            parent_step_key="deep_research_root",
            is_plan=True,
            status="success",
            data=[{"text": "Starting Deep Research"}],
            tool_name=None,
            progress_percent=0,
        )

        history: list[BaseMessage] = list(chat_history or [])
        history.append(HumanMessage(content=query))

        try:
            # Phase 1: Clarification (optional)
            if self._config.enable_clarification:
                async for event in self._phase_clarify(history, message_id, datetime_str):
                    yield event
                    if self._is_cancelled():
                        self._result.was_cancelled = True
                        return

            # Phase 2: Plan generation
            yield self._make_event(
                AgentEventType.TASKS_STEPS,
                message_id,
                step_key="deep_research_planning",
                parent_step_key="deep_research_root",
                is_plan=True,
                status="running",
                data=[{"text": "Generating Research Plan"}],
                tool_name=None,
                progress_percent=self._estimate_progress(),
            )
            async for event in self._phase_plan(query, history, message_id, datetime_str):
                yield event
                if self._is_cancelled():
                    self._result.was_cancelled = True
                    return

            if self._on_plan_ready and self._result.research_plan:
                try:
                    modified = await self._on_plan_ready(self._result.research_plan)
                    if modified:
                        self._result.research_plan = modified
                        logger.info("[deep-research] Plan modified by callback: %d chars", len(modified))
                except Exception:
                    logger.warning(
                        "[deep-research] on_plan_ready callback failed, continuing with original plan", exc_info=True
                    )

            yield self._make_event(
                AgentEventType.TASKS_STEPS,
                message_id,
                step_key="deep_research_planning",
                parent_step_key="deep_research_root",
                is_plan=True,
                status="success",
                data=[{"text": "Generating Research Plan"}],
                tool_name=None,
                progress_percent=self._estimate_progress(),
            )

            # Phase 2.5: Explore local knowledge (optional callback)
            if self._on_explore and self._result.research_plan:
                self._phase = DeepResearchPhase.EXPLORE
                yield self._make_event(
                    AgentEventType.TASKS_STEPS,
                    message_id,
                    step_key="deep_research_exploring",
                    parent_step_key="deep_research_root",
                    is_plan=True,
                    status="running",
                    data=[{"text": "Searching Local Knowledge"}],
                    tool_name=None,
                    progress_percent=self._estimate_progress(),
                )
                try:
                    local_context = await self._on_explore(self._result.research_plan)
                    if local_context:
                        self._result.local_context = local_context
                        logger.info(
                            "[deep-research] Explore found local context: %d chars",
                            len(local_context),
                        )
                    yield self._make_event(
                        AgentEventType.STATUS,
                        message_id,
                        data={
                            "phase": "explore",
                            "status": "complete",
                            "has_context": bool(local_context),
                            "context_chars": len(local_context) if local_context else 0,
                        },
                    )
                except Exception:
                    logger.warning(
                        "[deep-research] on_explore callback failed, continuing without local context",
                        exc_info=True,
                    )
                yield self._make_event(
                    AgentEventType.TASKS_STEPS,
                    message_id,
                    step_key="deep_research_exploring",
                    parent_step_key="deep_research_root",
                    is_plan=True,
                    status="success",
                    data=[{"text": "Searching Local Knowledge"}],
                    tool_name=None,
                    progress_percent=self._estimate_progress(),
                )

            # Phase 3: Research cycles
            yield self._make_event(
                AgentEventType.TASKS_STEPS,
                message_id,
                step_key="deep_research_researching",
                parent_step_key="deep_research_root",
                is_plan=True,
                status="running",
                data=[{"text": "Executing Research"}],
                tool_name=None,
                progress_percent=self._estimate_progress(),
            )
            async for event in self._phase_research(history, message_id, datetime_str):
                yield event
                if self._is_cancelled():
                    self._result.was_cancelled = True
                    return

            yield self._make_event(
                AgentEventType.TASKS_STEPS,
                message_id,
                step_key="deep_research_researching",
                parent_step_key="deep_research_root",
                is_plan=True,
                status="success",
                data=[{"text": "Executing Research"}],
                tool_name=None,
                progress_percent=self._estimate_progress(),
            )

            # Phase 4: Final report
            yield self._make_event(
                AgentEventType.TASKS_STEPS,
                message_id,
                step_key="deep_research_report",
                parent_step_key="deep_research_root",
                is_plan=True,
                status="running",
                data=[{"text": "Writing Report"}],
                tool_name=None,
                progress_percent=self._estimate_progress(),
            )
            async for event in self._phase_report(query, history, message_id, datetime_str):
                yield event

            yield self._make_event(
                AgentEventType.TASKS_STEPS,
                message_id,
                step_key="deep_research_report",
                parent_step_key="deep_research_root",
                is_plan=True,
                status="success",
                data=[{"text": "Writing Report"}],
                tool_name=None,
                progress_percent=100,
            )

            yield self._make_event(
                AgentEventType.TASKS_STEPS,
                message_id,
                step_key="deep_research_root",
                is_plan=True,
                status="success",
                data=[{"text": "Deep Research"}],
                tool_name=None,
                progress_percent=100,
            )

        except TimeoutError:
            logger.error("[deep-research] LLM call timeout in phase %s", self._phase.value)
            self._result.error = f"LLM timeout in {self._phase.value} phase"
            yield self._make_event(
                AgentEventType.ERROR, message_id, error=self._result.error, error_type="TimeoutError"
            )
        except Exception as e:
            logger.error("[deep-research] Unexpected error in phase %s: %s", self._phase.value, e, exc_info=True)
            self._result.error = f"{type(e).__name__}: {e}"
            yield self._make_event(AgentEventType.ERROR, message_id, error=str(e), error_type=type(e).__name__)
        finally:
            self._result.total_duration_seconds = time.time() - self._start_time
            model_name = getattr(self._llm, "model_name", "") or getattr(self._llm, "model", "") or ""
            estimate_cost(self._result, model_name)
            logger.info(
                "[deep-research] Finished in %.1fs, %d cycles, report=%d chars, tokens=%d/%d, cost=$%.4f, error=%s",
                self._result.total_duration_seconds,
                self._result.cycle_count,
                len(self._result.report),
                self._result.total_input_tokens,
                self._result.total_output_tokens,
                self._result.estimated_cost_usd,
                self._result.error,
            )
            if self._on_report_ready and self._result.report and not self._result.error:
                try:
                    await self._on_report_ready(self._result)
                except Exception:
                    logger.warning("[deep-research] on_report_ready callback failed", exc_info=True)

    @property
    def result(self) -> DeepResearchResult:
        return self._result
