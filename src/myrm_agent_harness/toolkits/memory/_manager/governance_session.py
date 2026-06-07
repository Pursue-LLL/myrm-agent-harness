"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._manager.helpers import _infer_preference_category
from myrm_agent_harness.toolkits.memory._manager.shared import (
    AnyMemory,
    ConsolidationConfig,
    CueFamily,
    HookRegistryProtocol,
    MemoryType,
    PendingRecord,
    PreferenceCandidate,
    SemanticMemory,
    _log_background_task_failure,
    logger,
    run_forgetting,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from myrm_agent_harness.toolkits.memory.session import MemorySession


class MemoryManagerGovernanceSessionMixin:
    async def submit_pending(self, memory: AnyMemory) -> str:
        """Submit a memory for approval. Returns pending ID, or '' if duplicate."""
        return await self._governance.submit_pending(memory)

    async def approve(self, pending_id: str) -> AnyMemory | None:
        """Approve a pending memory and persist to permanent storage."""
        return await self._governance.approve(
            pending_id,
            store_func=lambda memory: self.store(memory, _bypass_approval=True),
        )

    async def reject(self, pending_id: str) -> None:
        await self._governance.reject(pending_id)

    async def list_pending(self, *, limit: int = 50) -> list[PendingRecord]:
        return await self._governance.list_pending(limit=limit)

    async def count_pending(self) -> int:
        return await self._governance.count_pending()

    async def batch_approve(self, pending_ids: list[str]) -> tuple[int, list[str]]:
        """Returns (success_count, failed_ids)."""
        return await self._governance.batch_approve(pending_ids, approve_func=self.approve)

    async def batch_reject(self, pending_ids: list[str]) -> int:
        return await self._governance.batch_reject(pending_ids)

    def begin_session(
        self,
        chat_id: str,
        hook_registry: HookRegistryProtocol | None = None,
    ) -> MemorySession:
        from myrm_agent_harness.core.hooks.types import CallableHookDefinition, HookEvent
        from myrm_agent_harness.toolkits.memory.session import MemorySession
        from myrm_agent_harness.toolkits.memory.tool_capture import ToolMemoryCaptureHook

        if self._active_session is not None:
            self._active_session.discard()
        self._last_cited_memory_ids = []

        hook = ToolMemoryCaptureHook()
        if hook_registry is not None:
            if not any(
                isinstance(h, CallableHookDefinition) and h.fn.__name__ == "on_post_tool_failure"
                for h in hook_registry._hooks.get(HookEvent.POST_TOOL_USE_FAILURE, [])
            ):
                hook_registry.register(
                    HookEvent.POST_TOOL_USE_FAILURE, CallableHookDefinition(fn=hook.on_post_tool_failure)
                )
            if not any(
                isinstance(h, CallableHookDefinition) and h.fn.__name__ == "on_post_tool_use"
                for h in hook_registry._hooks.get(HookEvent.POST_TOOL_USE, [])
            ):
                hook_registry.register(HookEvent.POST_TOOL_USE, CallableHookDefinition(fn=hook.on_post_tool_use))
            if not any(
                isinstance(h, CallableHookDefinition) and h.fn.__name__ == "on_user_turn"
                for h in hook_registry._hooks.get(HookEvent.USER_TURN, [])
            ):
                hook_registry.register(HookEvent.USER_TURN, CallableHookDefinition(fn=hook.on_user_turn))

        self._active_session = MemorySession(manager=self, chat_id=chat_id, tool_capture_hook=hook)
        return self._active_session

    async def end_session(self) -> list[AnyMemory]:
        if self._active_session is None:
            return []
        session = self._active_session
        self._active_session = None
        persisted = await session.flush()
        self._session_count += 1
        if self._preference_strategy is not None:
            try:
                promoted = await self._preference_strategy.micro_rebuild()
                if promoted:
                    logger.info("Preference micro-rebuild: %d promoted to Active", promoted)
            except Exception as e:
                logger.warning("Preference micro-rebuild failed (non-fatal): %s", e)
        if self._session_count % self._config.forgetting_interval == 0 and self._vector is not None:
            task = asyncio.create_task(self._guarded_forgetting())
            task.add_done_callback(_log_background_task_failure)
        self._maybe_consolidate()
        return persisted

    async def check_session_recurrence(self, session_summary: str) -> None:
        """Check for topic recurrence across sessions and auto-store consolidated memory.

        Should be called by the agent after session end with a summary of the session's
        key topics (typically derived from user messages, not stored memories).

        This is a fire-and-forget operation — failures are logged and silently ignored.
        """
        if not self._recurrence_detector or not session_summary.strip():
            return
        await self._check_recurrence_and_store(session_summary)

    async def _check_recurrence_and_store(self, summary: str) -> None:
        """Run recurrence detection and store consolidated memory if triggered."""
        if self._recurrence_detector is None:
            return
        try:
            llm_func = self._build_recurrence_llm_func()
            result = await self._recurrence_detector.check_recurrence(summary, llm_func=llm_func)

            if not result.triggered or not result.consolidated_content:
                return

            logger.info(
                "Recurrence triggered (count=%d): storing consolidated memory",
                result.recurrence_count,
            )
            memory = SemanticMemory(
                content=result.consolidated_content,
                memory_type=MemoryType.SEMANTIC,
                importance=0.8,
                source="recurrence_consolidation",
            )
            await self.store(memory, _bypass_approval=True)
        except Exception as e:
            logger.warning("Recurrence check failed (non-fatal): %s", e)

    def _build_recurrence_llm_func(self) -> Callable[[str, str], Awaitable[str]] | None:
        """Build LLM function for recurrence consolidation using consolidation_llm."""
        if self._consolidation_llm is None:
            return None

        async def _call(system_prompt: str, user_prompt: str) -> str:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            response = await self._consolidation_llm.ainvoke(messages)  # type: ignore[union-attr]
            return str(response.content)

        return _call

    async def _guarded_forgetting(self) -> None:
        """Run forgetting with maintenance lock protection."""
        if self._maintenance_lock.locked():
            return
        async with self._maintenance_lock:
            if self._vector is None:
                return
            await run_forgetting(self._vector, self._config, self._graph)

    async def _submit_preference_candidate(self, memory: AnyMemory) -> None:
        """Submit a SemanticMemory with preference_type as a PreferenceCandidate."""
        if self._preference_strategy is None:
            return
        if not isinstance(memory, SemanticMemory):
            return
        if not memory.preference_type:
            return
        try:
            cue = (
                CueFamily(memory.preference_type)
                if memory.preference_type in ("explicit", "implicit")
                else CueFamily.INFERRED
            )
            candidate = PreferenceCandidate(
                key=memory.content[:80],
                value=memory.content,
                category=_infer_preference_category(memory),
                cue=cue,
                strength=memory.preference_strength or 0.5,
                memory_id=memory.id,
                content=memory.content,
            )
            await self._preference_strategy.submit_candidate(candidate)
        except Exception as e:
            logger.warning("Preference candidate submission failed (non-fatal): %s", e)

    def _maybe_consolidate(self) -> None:
        """Schedule background consolidation if enabled and LLM is available."""
        if self._consolidation_llm is None:
            return
        cfg = self._config.consolidation
        if not cfg.enabled:
            return
        if not (self.has_vector and self.has_relational):
            return
        task = asyncio.create_task(self._guarded_consolidation(cfg))
        task.add_done_callback(_log_background_task_failure)

    async def _guarded_consolidation(self, cfg: ConsolidationConfig) -> None:
        """Run consolidation with maintenance lock protection."""
        if self._maintenance_lock.locked():
            return
        async with self._maintenance_lock:
            await self._run_consolidation_safe(cfg)

    @property
    def active_session(self) -> MemorySession | None:
        return self._active_session
