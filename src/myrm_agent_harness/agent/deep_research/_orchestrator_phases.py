"""Phase implementations for Deep Research orchestrator.

Contains the clarification phase and research agent dispatch logic.

[INPUT]
- config::DeepResearchConfig (POS: configuration)
- helpers (POS: DeepResearchResult, utilities)
- prompts (POS: prompt templates)
- tools (POS: tool schemas)
- meta_tools.clarification (POS: structured clarification)

[OUTPUT]
- DeepResearchPhasesMixin: Mixin providing _phase_clarify and _dispatch_research_agents.

[POS]
Phase implementations for Deep Research orchestrator (clarification, dispatch).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.meta_tools.clarification import AskQuestionInput, QuestionItem
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .helpers import (
    accumulate_usage,
    build_research_subagent_config,
    extract_tool_calls,
)
from .prompts import CLARIFICATION_PROMPT
from myrm_agent_harness.agent.orchestration.signals.deep_research import (
    FINALIZE_TOOL_NAME,
    build_orchestrator_tools,
    build_signal_schema,
)

if TYPE_CHECKING:
    pass

logger = get_agent_logger(__name__)

__all__ = ["DeepResearchPhasesMixin"]


def _format_clarify_prompt(form: AskQuestionInput) -> str:
    """Format a clarification form into a human-readable prompt."""
    parts: list[str] = []
    if form.title:
        title = form.title.strip()
        if title:
            parts.append(title)

    multi_question = len(form.questions) > 1
    for index, question in enumerate(form.questions, 1):
        question_lines: list[str] = []
        prefix = f"{index}. " if multi_question else ""
        question_lines.append(f"{prefix}{question.prompt.strip()}")
        if question.options:
            for option in question.options:
                option_line = f"- {option.label.strip()}"
                if option.description:
                    option_line += f" — {option.description.strip()}"
                question_lines.append(option_line)
        parts.append("\n".join(question_lines))

    return "\n\n".join(part for part in parts if part).strip()


def _format_clarify_answer(form: AskQuestionInput, answer: object) -> str:
    """Format a user's answer to a clarification form."""

    def _render_value(value: object) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    if isinstance(answer, dict):
        prompt_map = {question.id: question.prompt for question in form.questions}
        rendered: list[str] = []

        for question in form.questions:
            value = answer.get(question.id)
            if value is None:
                continue
            rendered.append(f"{question.prompt}: {_render_value(value)}")

        for key, value in answer.items():
            if key not in prompt_map:
                rendered.append(f"{key}: {_render_value(value)}")

        return "\n".join(rendered).strip()

    return _render_value(answer).strip()


class DeepResearchPhasesMixin:
    """Mixin providing clarification phase and research agent dispatch.

    Expects host class to have:
    - _llm: BaseChatModel
    - _research_agent_llm: BaseChatModel | None
    - _config: DeepResearchConfig
    - _parent_tools: list[BaseTool]
    - _cancel_token: CancellationToken | None
    - _context: dict
    - _executor: object | None
    - _on_clarify: callback | None
    - _result: DeepResearchResult
    - _source_tracker: SourceTracker
    - _make_event(...): dict
    - _accumulate_child_usage(event): None
    """

    async def _phase_clarify(
        self, history: list[BaseMessage], message_id: str, datetime_str: str
    ) -> AsyncGenerator[dict[str, object]]:
        """Phase 1: Ask clarification questions if needed."""
        from .config import DeepResearchPhase

        self._phase = DeepResearchPhase.CLARIFY  # type: ignore[attr-defined]

        system_prompt = CLARIFICATION_PROMPT.format(current_datetime=datetime_str)
        messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *history]

        finalize_schema = [
            t for t in build_orchestrator_tools(include_think=False) if t["function"]["name"] == FINALIZE_TOOL_NAME
        ]  # type: ignore[index]

        ask_question_schema = build_signal_schema(
            "ask_question_tool",
            "Ask the user one or more clarifying questions using a structured form.",
            AskQuestionInput,
        )

        tools_to_bind = [*finalize_schema, ask_question_schema]
        bound_llm = self._llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined, arg-type]
        response = await asyncio.wait_for(
            bound_llm.ainvoke(messages),
            timeout=self._config.llm_call_timeout_seconds,  # type: ignore[attr-defined]
        )

        if not isinstance(response, AIMessage):
            return

        accumulate_usage(self._result, response)  # type: ignore[attr-defined]

        tool_calls = extract_tool_calls(response)
        if tool_calls and any(tc["name"] == FINALIZE_TOOL_NAME for tc in tool_calls):
            logger.info("[deep-research] Clarification skipped — query is detailed enough")
            return

        clarify_form: AskQuestionInput | None = None

        ask_tc = next((tc for tc in tool_calls if tc["name"] == "ask_question_tool"), None)
        if ask_tc:
            args = ask_tc.get("args", {})
            if isinstance(args, dict):
                try:
                    clarify_form = AskQuestionInput.model_validate(args)
                except Exception as exc:
                    logger.error("[deep-research] Failed to parse ask_question args: %s", exc)

        if clarify_form is None:
            raw_prompt = str(response.content).strip() if response.content else ""
            if not raw_prompt:
                return
            clarify_form = AskQuestionInput(
                title=None,
                questions=[QuestionItem(id="q1", prompt=raw_prompt)],
            )

        question_prompt = _format_clarify_prompt(clarify_form)
        if not question_prompt:
            return

        first_question = clarify_form.questions[0]
        event_data: dict[str, object] = {
            "phase": "clarify",
            "form": clarify_form.model_dump(),
            "prompt": first_question.prompt,
        }
        if clarify_form.title:
            event_data["title"] = clarify_form.title
        if len(clarify_form.questions) == 1 and first_question.options:
            event_data["options"] = [option.label for option in first_question.options]
            event_data["allow_multiple"] = first_question.allow_multiple

        yield self._make_event(  # type: ignore[attr-defined]
            AgentEventType.MESSAGE, message_id, data=question_prompt, metadata=event_data
        )

        if self._on_clarify:  # type: ignore[attr-defined]
            try:
                user_answer = await self._on_clarify(clarify_form)  # type: ignore[attr-defined]
                if user_answer:
                    history.append(AIMessage(content=question_prompt))
                    answer_str = _format_clarify_answer(clarify_form, user_answer)
                    history.append(HumanMessage(content=answer_str))
                    logger.info("[deep-research] Clarification answered: %d chars", len(answer_str))
            except Exception:
                logger.warning(
                    "[deep-research] on_clarify callback failed, skipping clarification",
                    exc_info=True,
                )

    async def _dispatch_research_agents(
        self,
        tasks: list[dict[str, str]],
        message_id: str,
        event_queue: asyncio.Queue[dict[str, object]] | None = None,
    ) -> list[str]:
        """Run research sub-agents in parallel, returning their result texts.

        When event_queue is provided, sub-agent status events are pushed to it
        for real-time streaming to the client.
        """
        from myrm_agent_harness.agent.sub_agents.builder import (
            build_standalone_agent,
            filter_tools,
        )

        config = build_research_subagent_config(self._config)  # type: ignore[attr-defined]
        sem = asyncio.Semaphore(self._config.max_concurrent_agents)  # type: ignore[attr-defined]

        def _push_status(idx: int, task_text: str, status: str, **extra: object) -> None:
            if event_queue is None:
                return
            event_queue.put_nowait(
                self._make_event(  # type: ignore[attr-defined]
                    AgentEventType.STATUS,
                    message_id,
                    data={
                        "phase": "research",
                        "agent_index": idx,
                        "agent_status": status,
                        "task": task_text[:120],
                        **extra,
                    },
                )
            )

        async def run_one(task_text: str, idx: int) -> str:
            async with sem:
                _push_status(idx, task_text, "started")
                messages: list[str] = []
                try:
                    filtered_tools = filter_tools(config, self._parent_tools)  # type: ignore[attr-defined]
                    child = build_standalone_agent(
                        llm=self._research_agent_llm or self._llm,  # type: ignore[attr-defined]
                        config=config,
                        tools=filtered_tools,
                        task_description=task_text,
                        executor=self._executor,  # type: ignore[attr-defined]
                    )
                    async for event in child.run(
                        query=task_text,
                        chat_history=[],
                        context=dict(self._context),  # type: ignore[attr-defined]
                        cancel_token=self._cancel_token,  # type: ignore[attr-defined]
                    ):
                        event_type = event.get("type")
                        if event_type == AgentEventType.MESSAGE.value:
                            content = event.get("data", "")
                            text = content if isinstance(content, str) else str(content)
                            messages.append(text)
                            if event_queue is not None:
                                event_queue.put_nowait(
                                    self._make_event(  # type: ignore[attr-defined]
                                        AgentEventType.STATUS,
                                        message_id,
                                        data={
                                            "phase": "research",
                                            "agent_index": idx,
                                            "agent_status": "streaming",
                                            "task": task_text[:120],
                                            "content": text,
                                        },
                                    )
                                )
                        elif event_type == AgentEventType.TOOL_START.value:
                            tool_name = event.get("tool_name", "")
                            _push_status(idx, task_text, "tool_call", tool_name=tool_name)
                        elif event_type == AgentEventType.SOURCES.value:
                            raw = event.get("data", [])
                            if isinstance(raw, list) and raw and event_queue is not None:
                                deduped = self._source_tracker.add_batch(raw)  # type: ignore[attr-defined]
                                if deduped:
                                    event_queue.put_nowait(
                                        self._make_event(  # type: ignore[attr-defined]
                                            AgentEventType.SOURCES, message_id, data=deduped
                                        )
                                    )
                        elif event_type == AgentEventType.MESSAGE_END.value:
                            self._accumulate_child_usage(event)  # type: ignore[attr-defined]
                        elif event_type == AgentEventType.ERROR.value:
                            err = event.get("error", "Unknown error")
                            logger.error("[deep-research] Research agent %d error: %s", idx, err)
                            if messages:
                                partial = "".join(messages)
                                self._result.agent_results.append(  # type: ignore[attr-defined]
                                    {"task": task_text, "result": partial, "partial": True}
                                )
                                _push_status(idx, task_text, "error", result_length=len(partial), partial=True)
                                return f"{partial}\n\n[Partial — agent encountered error: {err}]"
                            _push_status(idx, task_text, "error")
                            return f"[Research error: {err}]"

                    result_text = "".join(messages)
                    self._result.agent_results.append(  # type: ignore[attr-defined]
                        {"task": task_text, "result": result_text}
                    )
                    _push_status(idx, task_text, "complete", result_length=len(result_text))
                    logger.info("[deep-research] Agent %d completed: %d chars", idx, len(result_text))
                    return result_text or "[No findings]"

                except Exception as e:
                    logger.error("[deep-research] Research agent %d failed: %s", idx, e, exc_info=True)
                    if messages:
                        partial = "".join(messages)
                        self._result.agent_results.append(  # type: ignore[attr-defined]
                            {"task": task_text, "result": partial, "partial": True}
                        )
                        _push_status(idx, task_text, "error", result_length=len(partial), partial=True)
                        return f"{partial}\n\n[Partial — agent failed: {e}]"
                    _push_status(idx, task_text, "error")
                    return f"[Research agent failed: {e}]"

        coros = [run_one(t["task"], i) for i, t in enumerate(tasks)]
        return list(await asyncio.gather(*coros))

    async def _phase_report(
        self,
        query: str,
        history: list[BaseMessage],
        message_id: str,
        datetime_str: str,
    ) -> AsyncGenerator[dict[str, object]]:
        """Phase 4: Generate the final comprehensive report with streaming."""
        from .config import DeepResearchPhase
        from .helpers import accumulate_usage
        from .prompts import FINAL_REPORT_PROMPT, FINAL_REPORT_QUERY

        self._phase = DeepResearchPhase.REPORT  # type: ignore[attr-defined]

        system_prompt = FINAL_REPORT_PROMPT.format(current_datetime=datetime_str)
        user_query = FINAL_REPORT_QUERY.format(
            research_plan=self._result.research_plan  # type: ignore[attr-defined]
        )

        research_context = self._format_research_context()

        messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            *history,
        ]

        if research_context:
            messages.append(HumanMessage(content=f"# Research Findings\n\n{research_context}"))

        messages.append(HumanMessage(content=user_query))

        report_chunks: list[str] = []
        report_usage_captured = False
        truncated = False
        try:
            async with asyncio.timeout(
                self._config.report_timeout_seconds  # type: ignore[attr-defined]
            ):
                async for chunk in self._llm.astream(messages):  # type: ignore[attr-defined]
                    content = str(chunk.content) if chunk.content else ""
                    if content:
                        report_chunks.append(content)
                        yield self._make_event(  # type: ignore[attr-defined]
                            AgentEventType.MESSAGE,
                            message_id,
                            data=content,
                            metadata={"phase": "report"},
                        )
                    usage = getattr(chunk, "usage_metadata", None)
                    if usage and isinstance(usage, dict) and usage.get("input_tokens"):
                        accumulate_usage(self._result, chunk)  # type: ignore[attr-defined]
                        report_usage_captured = True
        except TimeoutError:
            truncated = True
            logger.warning(
                "[deep-research] Report generation timed out after %ds",
                self._config.report_timeout_seconds,  # type: ignore[attr-defined]
            )

        self._result.report = "".join(report_chunks)  # type: ignore[attr-defined]

        if not report_usage_captured and self._result.report:  # type: ignore[attr-defined]
            input_chars = sum(len(str(m.content)) for m in messages)
            estimated_input = input_chars // 4
            estimated_output = len(self._result.report) // 4  # type: ignore[attr-defined]
            self._result.total_input_tokens += estimated_input  # type: ignore[attr-defined]
            self._result.total_output_tokens += estimated_output  # type: ignore[attr-defined]
            logger.info(
                "[deep-research] Report token usage estimated (no streaming usage): ~%d input, ~%d output",
                estimated_input,
                estimated_output,
            )

        end_data: dict[str, object] = {
            "phase": "report",
            "report_length": len(self._result.report),  # type: ignore[attr-defined]
            "progress_percent": 100,
        }
        if truncated:
            end_data["truncated"] = True
            end_data["truncated_reason"] = "report_timeout"

        yield self._make_event(  # type: ignore[attr-defined]
            AgentEventType.MESSAGE_END, message_id, data=end_data
        )

    def _format_research_context(self) -> str:
        """Format all research agent results into a single context block.

        Applies max_report_context_chars budget. When the total exceeds the
        limit, the earliest tasks are truncated first (most recent results are
        typically the most refined and valuable for the final report).
        """
        if not self._result.agent_results:  # type: ignore[attr-defined]
            return ""

        limit = self._config.max_report_context_chars  # type: ignore[attr-defined]
        separator = "\n\n---\n\n"

        parts: list[str] = []
        for i, entry in enumerate(self._result.agent_results, 1):  # type: ignore[attr-defined]
            task = entry.get("task", "Unknown task")
            result = entry.get("result", "No result")
            parts.append(f"## Research Task {i}: {task}\n\n{result}")

        full = separator.join(parts)
        if len(full) <= limit:
            return full

        kept: list[str] = []
        budget = limit
        for part in reversed(parts):
            cost = len(part) + len(separator)
            if budget >= cost:
                kept.append(part)
                budget -= cost
            elif budget > len(separator) + 100:
                trunc = part[: budget - len(separator) - 50]
                trunc += "\n\n[Truncated — prioritizing most recent research]"
                kept.append(trunc)
                break
            else:
                break

        kept.reverse()
        logger.info(
            "[deep-research] Report context: %d/%d tasks kept, %d/%d chars",
            len(kept),
            len(parts),
            len(separator.join(kept)),
            len(full),
        )
        return separator.join(kept)
