"""SkillAgent session-end review logic — skill review, wiki archive, recurrence detection.

[INPUT]
- skills.evolution.review (POS: Skill review evaluator, pruner, reviewer)
- _skill_agent_context (POS: Background task tracking)

[OUTPUT]
- SkillAgentReviewMixin: Mixin providing session-end review methods for SkillAgent

[POS]
Session-end review mixin for SkillAgent. Handles background post-session tasks:
skill review, wiki archive, and recurrence detection.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from myrm_agent_harness.agent._skill_agent_context import track_background_task
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.agent.skills import SkillMetadata
    from myrm_agent_harness.agent.types import AgentRunStatistics
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.wiki import WikiCompiler, WikiStructure
    from myrm_agent_harness.utils.chat_utils import ChatHistoryReq

logger = get_agent_logger(__name__)


class SkillAgentReviewMixin:
    """Mixin providing session-end review methods for SkillAgent.

    Requires the following attributes from SkillAgent:
    - last_run_stats: AgentRunStatistics | None
    - _wiki_compiler: WikiCompiler | None
    - _wiki_structure: WikiStructure | None
    - _extraction_llm: BaseChatModel | None
    - _on_skill_review_ready: Callable | None
    - _user_id: str | None
    - _last_context: dict | None
    - _agent: LangGraph agent instance
    - llm: BaseChatModel
    - config: AgentRuntimeConfig
    """

    @staticmethod
    def _build_recurrence_summary(
        query: str | list[dict[str, object]] | object,
        assistant_chunks: list[str],
    ) -> str:
        """Extract a concise topic summary from user query for recurrence detection."""
        if isinstance(query, str):
            user_text = query
        elif isinstance(query, list):
            user_parts = [str(m.get("content", "")) for m in query if m.get("role") == "user"]
            user_text = " ".join(user_parts)
        else:
            return ""
        user_text = user_text.strip()[:300]
        if not user_text:
            return ""
        return user_text

    def _maybe_archive_to_wiki(
        self,
        query: str | list[dict[str, object]] | object,
        assistant_chunks: list[str],
    ) -> None:
        """Archive conversation content to wiki if quality threshold is met (background task)."""
        wiki_compiler: WikiCompiler | None = getattr(self, "_wiki_compiler", None)
        wiki_structure: WikiStructure | None = getattr(self, "_wiki_structure", None)
        if wiki_compiler is None or wiki_structure is None:
            return

        reply = "".join(assistant_chunks)
        if len(reply) < 500:
            return

        query_text = query if isinstance(query, str) else str(query)
        archive_content = f"# Query\n\n{query_text}\n\n# Response\n\n{reply}"
        config = getattr(self, "config", None)

        async def _archive() -> None:
            try:
                assert wiki_structure is not None
                assert wiki_compiler is not None

                chat_id = getattr(config, "chat_id", None) or "unknown"
                raw_path = wiki_structure.get_raw_file_path(f"conversation_{chat_id}.md")
                raw_path.write_text(archive_content, encoding="utf-8")
                await wiki_compiler.compile_all()
                logger.info("Wiki auto-archive completed: %s", raw_path.name)
            except Exception as e:
                logger.warning("Wiki auto-archive failed: %s", e)

        task = asyncio.create_task(_archive())
        track_background_task(task)
        logger.info("Wiki auto-archive scheduled (content=%d chars)", len(archive_content))

    def _should_trigger_skill_review(self, query: str | list[dict[str, object]] | object) -> bool:
        """Determine if a background skill review should be triggered.

        Uses HeartbeatEvaluator for expression volume + task complexity assessment.
        Includes Pre-Screener to block trajectories that completely failed.
        """
        stats: AgentRunStatistics | None = getattr(self, "last_run_stats", None)
        if stats is None:
            return False

        # --- Pre-Screener Logic ---
        if stats.was_cancelled:
            logger.debug("Skill review skipped: run was cancelled.")
            return False

        if stats.error_message:
            logger.debug("Skill review skipped: run has fatal framework error.")
            return False

        try:
            from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor

            executor = get_executor()
            if executor and hasattr(executor, "metrics"):
                metrics = executor.metrics
                if metrics.total_executions > 0 and metrics.total_success == 0:
                    logger.info("Skill review skipped (Pre-Screener): Trajectory had 0 successful tool executions.")
                    return False
        except Exception as e:
            logger.debug("Skill review pre-screener failed to check executor metrics: %s", e)
        # --------------------------

        tool_call_count = stats.tool_call_count

        if isinstance(query, str):
            expression_length = len(query)
        elif hasattr(query, "resume"):
            resume_val = getattr(query, "resume", "")
            expression_length = len(str(resume_val))
        else:
            try:
                expression_length = sum(
                    len(str(item.get("text", "")))
                    for item in query  # type: ignore[union-attr]
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            except TypeError:
                expression_length = 0

        from myrm_agent_harness.agent.skills.evolution.review.evaluator import (
            HeartbeatEvaluator,
        )

        evaluator = HeartbeatEvaluator()
        return evaluator.should_trigger_review(tool_call_count, expression_length)

    async def _trigger_background_skill_review(
        self,
        query: str | list[dict[str, object]] | object,
        chat_history: ChatHistoryReq | list[BaseMessage] | None,
        assistant_chunks: list[str],
        active_skills: list[str] | None = None,
    ) -> None:
        """Trigger background skill review task (async, non-blocking).

        Review pipeline:
        1. Prune conversation history (reduce token cost).
        2. Call LLM to summarize experience.
        3. Generate SkillDraft or SemanticMemory.

        Uses extraction_llm (cheap model) to control cost.
        """
        from langchain_core.messages import AIMessage, HumanMessage

        from myrm_agent_harness.agent.skills.evolution.review.pruner import (
            prune_trajectory,
        )
        from myrm_agent_harness.agent.skills.evolution.review.reviewer import (
            review_trajectory_with_llm,
        )
        from myrm_agent_harness.utils.chat_utils import convert_chat_history_simple

        messages = convert_chat_history_simple(chat_history) if chat_history else []

        ctx = getattr(self, "_last_context", None) or {}
        user_id = getattr(self, "_user_id", None)
        session_user_id = str(ctx.get("user_id") or user_id or "")
        session_agent_id = str(ctx.get("agent_id") or user_id or "")
        session_chat_id = str(ctx.get("chat_id") or ctx.get("session_id") or "default")

        agent_instance = getattr(self, "_agent", None)
        config = {"configurable": {"thread_id": session_chat_id}}
        fetched_state = False
        query_text = query if isinstance(query, str) else "[multimodal]"

        if agent_instance is not None:
            try:
                state_snapshot = await agent_instance.aget_state(config)
                if state_snapshot and state_snapshot.values and "messages" in state_snapshot.values:
                    messages = list(state_snapshot.values["messages"])
                    fetched_state = True
            except Exception as e:
                logger.warning("Failed to fetch full state for skill review: %s", e)

        if not fetched_state:
            messages.append(HumanMessage(content=query_text))

            assistant_reply = "".join(assistant_chunks)
            if assistant_reply:
                messages.append(AIMessage(content=assistant_reply))

        if len(messages) < 2:
            return

        llm: BaseChatModel = self.llm
        extraction_llm: BaseChatModel | None = getattr(self, "_extraction_llm", None)
        review_llm = extraction_llm or llm

        all_skills_catalog: str | None = None
        get_cached = getattr(self, "_get_cached_skills", None)
        if get_cached is not None:
            try:
                cached: list[SkillMetadata] = await get_cached()
                if cached:
                    all_skills_catalog = "\n".join(f"- {s.name} — {s.description}" for s in cached)
            except Exception:
                pass

        on_skill_review_ready: Callable[[dict[str, object]], None] | None = getattr(
            self, "_on_skill_review_ready", None
        )

        async def _execute_review() -> None:
            try:
                trajectory_skeleton = prune_trajectory(messages)
                if not trajectory_skeleton:
                    return

                result = await review_trajectory_with_llm(
                    trajectory_skeleton,
                    review_llm,
                    active_skills=active_skills,
                    all_skills_catalog=all_skills_catalog,
                    original_goal=query_text,
                )
                if result and result.has_value:
                    result.user_id = session_user_id
                    result.agent_id = session_agent_id
                    result.chat_id = session_chat_id
                    logger.info(
                        "Skill review result: type=%s, content=%s",
                        result.result_type,
                        result.content or result.skill_name,
                    )
                    if on_skill_review_ready:
                        try:
                            on_skill_review_ready(result.to_dict())
                        except Exception as cb_err:
                            logger.error("Skill review callback failed: %s", cb_err)

            except Exception as e:
                logger.error("Background skill review failed: %s", e, exc_info=True)

        task = asyncio.create_task(_execute_review())
        track_background_task(task)

    async def _cleanup_session(
        self,
        query: str | list[dict[str, object]] | object,
        chat_history: ChatHistoryReq | list[BaseMessage] | None,
        assistant_chunks: list[str],
        active_skills: list[str] | None = None,
    ) -> None:
        """Session-end cleanup: memory flush, auto-extraction, wiki archive, skill review.

        SessionEnd hook is triggered by stream_executor.py finally block; not duplicated here.
        All background tasks (memory extraction, wiki archive, skill review) run async.
        """
        memory_manager: MemoryManager | None = getattr(self, "memory_manager", None)
        session_chat_id: str | None = None

        if memory_manager is not None:
            session = memory_manager.active_session
            session_chat_id = session.chat_id if session else None
            try:
                persisted = await memory_manager.end_session()
                if persisted:
                    logger.info("Memory session flush: %d memories persisted", len(persisted))
            except Exception as e:
                logger.warning("Memory session flush failed: %s", e)

            if getattr(self, "_enable_memory_auto_extraction", False):
                from myrm_agent_harness.agent._internals.memory_extraction import (
                    auto_extract_memories,
                )
                from myrm_agent_harness.agent.middlewares._session_context import (
                    get_privacy_policy,
                )

                privacy = get_privacy_policy()
                llm: BaseChatModel = self.llm
                extraction_llm: BaseChatModel | None = getattr(self, "_extraction_llm", None)
                task = asyncio.create_task(
                    auto_extract_memories(
                        query,
                        chat_history,
                        memory_manager,
                        llm,
                        extraction_llm=extraction_llm,
                        source_chat_id=session_chat_id,
                        assistant_reply="".join(assistant_chunks),
                        deep_scan=privacy.deep_scan,
                    )
                )
                track_background_task(task)

            recurrence_summary = self._build_recurrence_summary(query, assistant_chunks)
            if recurrence_summary:
                recurrence_task = asyncio.create_task(memory_manager.check_session_recurrence(recurrence_summary))
                track_background_task(recurrence_task)

        on_session_cleanup = getattr(self, "_on_session_cleanup", None)
        if on_session_cleanup is not None:
            if isinstance(query, str):
                messages_for_hook: list[dict[str, object]] = [{"role": "user", "content": query}]
            elif isinstance(query, list):
                messages_for_hook = [
                    {
                        "role": str(m.get("role", "user")),
                        "content": str(m.get("content", "")),
                    }
                    for m in query
                ]
            else:
                messages_for_hook = []
            messages_for_hook.append({"role": "assistant", "content": "".join(assistant_chunks)})

            async def _run_session_cleanup() -> None:
                try:
                    await on_session_cleanup(messages_for_hook, session_chat_id)
                except Exception as e:
                    logger.warning("Session cleanup hook failed: %s", e)

            cleanup_task = asyncio.create_task(_run_session_cleanup())
            track_background_task(cleanup_task)

        self._maybe_archive_to_wiki(query, assistant_chunks)

        if self._should_trigger_skill_review(query):
            await self._trigger_background_skill_review(query, chat_history, assistant_chunks, active_skills)

        # Reset active skill reference
        if hasattr(self, "_active_skill"):
            self._active_skill = None
