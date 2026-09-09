"""Deep Research plan and research-loop phase implementations.

[POS]
Mixin: _phase_plan and _phase_research for DeepResearchOrchestrator.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.orchestration.signals.deep_research import (
    FINALIZE_TOOL_NAME,
    build_orchestrator_tools,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.memory.working_tree import (
    ConflictType,
    EvidenceTree,
    FastContradictionDetector,
    TreeRepairEngine,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .helpers import accumulate_usage, create_evidence_node_from_task_result, extract_tool_calls

if TYPE_CHECKING:
    pass

logger = get_agent_logger(__name__)


class DeepResearchPlanResearchMixin:
    """Mixin providing plan generation and research execution loop."""

    async def _phase_plan(
        self, query: str, history: list[BaseMessage], message_id: str, datetime_str: str
    ) -> AsyncGenerator[dict[str, object]]:
        """Phase 2: Generate research plan."""
        from .config import DeepResearchPhase
        from .prompts import RESEARCH_PLAN_PROMPT, RESEARCH_PLAN_REMINDER

        self._phase = DeepResearchPhase.PLAN  # type: ignore[attr-defined]

        system_prompt = RESEARCH_PLAN_PROMPT.format(current_datetime=datetime_str)
        messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            *history,
            HumanMessage(content=RESEARCH_PLAN_REMINDER),
        ]

        response = await asyncio.wait_for(
            self._llm.ainvoke(messages),  # type: ignore[attr-defined]
            timeout=self._config.llm_call_timeout_seconds,  # type: ignore[attr-defined]
        )
        accumulate_usage(self._result, response)  # type: ignore[attr-defined]
        # 兼容 reasoning 模型 content 空回退（Qwen3/DeepSeek-R1 等）
        plan = extract_answer_text(response).strip()
        self._result.research_plan = plan  # type: ignore[attr-defined]

        if plan:
            yield self._make_event(  # type: ignore[attr-defined]
                AgentEventType.STATUS, message_id, data={"phase": "plan", "plan": plan}
            )

        logger.info("[deep-research] Plan generated: %d chars", len(plan))

    async def _phase_research(
        self, history: list[BaseMessage], message_id: str, datetime_str: str
    ) -> AsyncGenerator[dict[str, object]]:
        """Phase 3: Orchestrator loop — dispatch research agents and think."""

        from myrm_agent_harness.agent.orchestration.signals.deep_research import (
            DISPATCH_TOOL_NAME,
            THINK_TOOL_NAME,
        )

        from .config import DeepResearchPhase
        from .helpers import (
            MAX_EMPTY_ITERATIONS,
            compact_orch_messages,
            truncate_for_orchestrator,
        )
        from .prompts import (
            FIRST_CYCLE_REMINDER,
            build_orchestrator_prompt,
            build_orchestrator_reminder,
        )

        self._phase = DeepResearchPhase.RESEARCH  # type: ignore[attr-defined]
        cycle = 0
        empty_iterations = 0

        max_cycles = (
            self._config.max_cycles_reasoning  # type: ignore[attr-defined]
            if self._is_reasoning  # type: ignore[attr-defined]
            else self._config.max_cycles  # type: ignore[attr-defined]
        )
        include_think = not self._is_reasoning  # type: ignore[attr-defined]
        tool_schemas = build_orchestrator_tools(include_think=include_think)

        local_ctx = self._result.local_context  # type: ignore[attr-defined]
        has_local_ctx = bool(local_ctx)

        format_kwargs: dict[str, str] = {
            "current_datetime": datetime_str,
            "current_cycle": "0",
            "max_cycles": str(max_cycles),
            "research_plan": self._result.research_plan,  # type: ignore[attr-defined]
        }
        if has_local_ctx:
            format_kwargs["local_context"] = local_ctx

        system_prompt = build_orchestrator_prompt(
            self._is_reasoning,  # type: ignore[attr-defined]
            has_local_context=has_local_ctx,
        ).format(**format_kwargs)
        reminder = build_orchestrator_reminder(self._is_reasoning)  # type: ignore[attr-defined]

        orch_messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            *history,
            HumanMessage(content=reminder),
        ]

        evidence_tree = EvidenceTree(
            root_id="root_plan", root_claim=self._result.research_plan or "Deep Research Goal"
        )
        detector = FastContradictionDetector(arbitrator_llm=self._llm)
        repair_engine = TreeRepairEngine(tree=evidence_tree)

        while cycle < max_cycles:
            if self._is_cancelled() or self._is_timed_out():  # type: ignore[attr-defined]
                logger.warning(
                    "[deep-research] Research loop terminated: cancelled=%s, timeout=%s",
                    self._is_cancelled(),  # type: ignore[attr-defined]
                    self._is_timed_out(),  # type: ignore[attr-defined]
                )
                break

            bound_llm = self._llm.bind_tools(tool_schemas)  # type: ignore[attr-defined]
            response = await asyncio.wait_for(
                bound_llm.ainvoke(orch_messages),
                timeout=self._config.llm_call_timeout_seconds,  # type: ignore[attr-defined]
            )

            if not isinstance(response, AIMessage):
                break

            accumulate_usage(self._result, response)  # type: ignore[attr-defined]
            tool_calls = extract_tool_calls(response)
            if not tool_calls:
                logger.warning("[deep-research] Orchestrator produced no tool calls, ending loop")
                break

            orch_messages.append(response)

            dispatch_tasks: list[dict[str, str]] = []
            should_finalize = False

            for tc in tool_calls:
                name = str(tc["name"])
                args = tc["args"] if isinstance(tc["args"], dict) else {}
                tc_id = str(tc["id"])

                if name == THINK_TOOL_NAME:
                    reasoning_text = str(args.get("reasoning", ""))
                    logger.debug("[deep-research] Think: %s", reasoning_text[:200])
                    orch_messages.append(
                        ToolMessage(content="Thinking noted. Continue with research or finalize.", tool_call_id=tc_id)
                    )
                    yield self._make_event(  # type: ignore[attr-defined]
                        AgentEventType.STATUS, message_id, data={"phase": "think", "reasoning": reasoning_text}
                    )

                elif name == DISPATCH_TOOL_NAME:
                    task_text = str(args.get("task", ""))
                    dispatch_tasks.append({"task": task_text, "tc_id": tc_id})

                elif name == FINALIZE_TOOL_NAME:
                    should_finalize = True
                    orch_messages.append(ToolMessage(content="Report generation will begin.", tool_call_id=tc_id))

            if dispatch_tasks:
                empty_iterations = 0
                agent_event_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
                dispatch_future = asyncio.ensure_future(
                    self._dispatch_research_agents(dispatch_tasks, message_id, agent_event_queue)
                )
                while not dispatch_future.done():
                    try:
                        event = await asyncio.wait_for(agent_event_queue.get(), timeout=0.5)
                        yield event
                    except TimeoutError:
                        continue
                while not agent_event_queue.empty():
                    yield agent_event_queue.get_nowait()
                results = dispatch_future.result()
                for task_idx, (task_info, result_text) in enumerate(zip(dispatch_tasks, results, strict=True)):
                    orch_messages.append(
                        ToolMessage(content=truncate_for_orchestrator(result_text), tool_call_id=task_info["tc_id"])
                    )
                    active_nodes = evidence_tree.get_active_nodes()
                    candidate_node = create_evidence_node_from_task_result(
                        cycle=cycle,
                        task_idx=task_idx,
                        task_text=task_info["task"],
                        result_text=result_text,
                        existing_nodes=active_nodes,
                    )
                    verdict = await detector.acheck_conflict(
                        new_claim=candidate_node.claim,
                        new_summary=candidate_node.bounded_summary.summary,
                        existing_nodes=active_nodes,
                        new_content_hash=candidate_node.source.content_hash,
                    )

                    if (
                        verdict.conflict_type in (ConflictType.CONTRADICTION, ConflictType.TEMPORAL_UPDATE)
                        and verdict.conflicting_node_id
                    ):
                        repair_res = repair_engine.apply_repair(
                            target_node_id=verdict.conflicting_node_id,
                            new_claim=candidate_node.claim,
                            new_summary=candidate_node.bounded_summary,
                            new_source=candidate_node.source,
                            conflict_type=verdict.conflict_type,
                            reason=verdict.reason,
                        )
                        logger.info(
                            "[deep-research] Working tree repair applied: target=%s, pruned=%s, disputed=%s",
                            repair_res.target_node_id,
                            repair_res.pruned_node_ids,
                            repair_res.is_disputed,
                        )
                        yield self._make_event(  # type: ignore[attr-defined]
                            AgentEventType.STATUS,
                            message_id,
                            data={
                                "phase": "evidence_repair",
                                "target_node_id": repair_res.target_node_id,
                                "pruned_nodes": repair_res.pruned_node_ids,
                                "is_disputed": repair_res.is_disputed,
                                "summary": repair_res.resolution_summary,
                            },
                        )
                    else:
                        evidence_tree.add_node(candidate_node)

                self._result.evidence_tree = evidence_tree.to_dict()  # type: ignore[attr-defined]
                cycle += 1
                self._result.cycle_count = cycle  # type: ignore[attr-defined]
                self._update_cost_estimate()  # type: ignore[attr-defined]

                yield self._make_event(  # type: ignore[attr-defined]
                    AgentEventType.STATUS,
                    message_id,
                    data={
                        "phase": "research",
                        "cycle": cycle,
                        "max_cycles": max_cycles,
                        "current_cost_usd": self._result.estimated_cost_usd,  # type: ignore[attr-defined]
                        "progress_percent": self._estimate_progress(),  # type: ignore[attr-defined]
                    },
                )

                if self._on_cycle_complete:  # type: ignore[attr-defined]
                    try:
                        current_results = [
                            {"task": t["task"], "result": r[:500]} for t, r in zip(dispatch_tasks, results, strict=True)
                        ]
                        guidance = await self._on_cycle_complete(cycle, current_results)  # type: ignore[attr-defined]
                        if guidance is not None:
                            if guidance.stop:
                                logger.info("[deep-research] Early stop requested by callback at cycle %d", cycle)
                                break
                            if guidance.guidance:
                                orch_messages.append(HumanMessage(content=f"[User guidance]: {guidance.guidance}"))
                                logger.info(
                                    "[deep-research] Guidance injected at cycle %d: %d chars",
                                    cycle,
                                    len(guidance.guidance),
                                )
                    except Exception:
                        logger.warning(
                            "[deep-research] on_cycle_complete callback failed at cycle %d, continuing",
                            cycle,
                            exc_info=True,
                        )

                if self._is_over_budget():  # type: ignore[attr-defined]
                    logger.warning(
                        "[deep-research] Budget exceeded ($%.4f >= $%.2f) at cycle %d — stopping research",
                        self._result.estimated_cost_usd,  # type: ignore[attr-defined]
                        self._config.max_budget_usd,  # type: ignore[attr-defined]
                        cycle,
                    )
                    yield self._make_event(  # type: ignore[attr-defined]
                        AgentEventType.STATUS,
                        message_id,
                        data={
                            "phase": "research",
                            "budget_event": "exceeded",
                            "current_cost_usd": self._result.estimated_cost_usd,  # type: ignore[attr-defined]
                            "budget_usd": self._config.max_budget_usd,  # type: ignore[attr-defined]
                            "percent_used": round(
                                self._result.estimated_cost_usd  # type: ignore[attr-defined]
                                / self._config.max_budget_usd  # type: ignore[attr-defined]
                                * 100,
                                1,
                            ),
                        },
                    )
                    break
                if not getattr(self, "_budget_warning_sent", False) and self._is_budget_warning():  # type: ignore[attr-defined]
                    self._budget_warning_sent = True  # type: ignore[attr-defined]
                    logger.warning(
                        "[deep-research] Budget warning ($%.4f >= %.0f%% of $%.2f) at cycle %d",
                        self._result.estimated_cost_usd,  # type: ignore[attr-defined]
                        self._config.budget_warning_threshold * 100,  # type: ignore[attr-defined]
                        self._config.max_budget_usd,  # type: ignore[attr-defined]
                        cycle,
                    )
                    yield self._make_event(  # type: ignore[attr-defined]
                        AgentEventType.STATUS,
                        message_id,
                        data={
                            "phase": "research",
                            "budget_event": "warning",
                            "current_cost_usd": self._result.estimated_cost_usd,  # type: ignore[attr-defined]
                            "budget_usd": self._config.max_budget_usd,  # type: ignore[attr-defined]
                            "percent_used": round(
                                self._result.estimated_cost_usd  # type: ignore[attr-defined]
                                / self._config.max_budget_usd  # type: ignore[attr-defined]
                                * 100,
                                1,
                            ),
                        },
                    )

                if cycle == 1:
                    orch_messages.append(HumanMessage(content=FIRST_CYCLE_REMINDER))

                cycle_format_kwargs: dict[str, str] = {
                    "current_datetime": datetime_str,
                    "current_cycle": str(cycle),
                    "max_cycles": str(max_cycles),
                    "research_plan": self._result.research_plan,  # type: ignore[attr-defined]
                }
                if has_local_ctx:
                    cycle_format_kwargs["local_context"] = local_ctx
                orch_messages[0] = SystemMessage(
                    content=build_orchestrator_prompt(
                        self._is_reasoning,  # type: ignore[attr-defined]
                        has_local_context=has_local_ctx,
                    ).format(**cycle_format_kwargs)
                )

                compact_orch_messages(orch_messages)
            else:
                empty_iterations += 1
                if empty_iterations >= MAX_EMPTY_ITERATIONS:
                    logger.warning(
                        "[deep-research] %d consecutive iterations without dispatch, forcing finalize",
                        empty_iterations,
                    )
                    break

            if should_finalize:
                logger.info("[deep-research] Orchestrator called finalize_report at cycle %d", cycle)
                break

        logger.info("[deep-research] Research phase complete after %d cycles", cycle)
