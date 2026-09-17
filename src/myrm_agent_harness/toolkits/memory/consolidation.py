"""Hyper Consolidation Memory Block subsystem.

Performs post-session cognitive distillation and assetization in the background.
Abstracts runtime task outcomes into structured TaskDigestMemory and crystallizes
verified self-healing error avoidance traps into durable ProceduralMemory.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    SubtaskStatus,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemoryLifecycle,
    MemoryStatus,
    ProceduralMemory,
    RuleSource,
    TaskDigestMemory,
    ToolRulePriority,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.session_post_process import SessionCleanupTask

logger = logging.getLogger(__name__)


class HyperConsolidator:
    """Post-session memory consolidator distilling working memory into long-term assets."""

    def __init__(self, memory_manager: MemoryManager | None = None) -> None:
        self._memory_manager = memory_manager

    async def consolidate_session(
        self,
        messages: Sequence[dict[str, str]],
        chat_id: str | None,
    ) -> tuple[TaskDigestMemory | None, list[ProceduralMemory]]:
        """Run post-session consolidation pipeline on the active working memory state.

        Returns:
            Tuple of (TaskDigestMemory | None, list of created ProceduralMemory rules).
        """
        state = LocalWorkingMemoryBlock.get_state()
        if state is None or not state.goal:
            logger.debug("Hyper consolidation bypassed: no active working goal found.")
            LocalWorkingMemoryBlock.reset()
            return None, []

        session_id = chat_id or "default"

        # Gatekeeper Filter: Bypass trivial queries (turns <= 1 and no subtasks or traps)
        has_subtasks = len(state.subtasks) > 0
        has_traps = len(state.traps) > 0
        if state.active_turn <= 1 and not has_subtasks and not has_traps:
            logger.debug("Hyper consolidation gatekeeper: trivial turn bypassed for session %s", session_id)
            LocalWorkingMemoryBlock.reset()
            return None, []

        # 1. Distill TaskDigestMemory
        completed_steps = [
            item.title
            for item in state.subtasks
            if item.status == SubtaskStatus.COMPLETED
        ]
        key_findings = [
            f"{k}: {v}" for k, v in state.scratchpad.items()
        ]
        error_lessons = [
            f"{trap.tool_name or 'general'}: {trap.avoidance_rule}"
            for trap in state.traps
        ]

        digest_status = state.status
        if digest_status not in ("completed", "interrupted", "failed"):
            digest_status = "completed"

        task_digest = TaskDigestMemory(
            id=f"digest-{session_id}-{state.active_turn}",
            task_goal=state.goal,
            status=digest_status,  # type: ignore[arg-type]
            completed_steps=completed_steps,
            artifact_paths=[],
            artifact_hashes={},
            key_findings=key_findings,
            error_lessons=error_lessons,
            tool_call_count=state.active_turn,
            source_session_id=session_id,
            lifecycle=MemoryLifecycle.new_task_digest(),
        )

        # 2. Distill ProceduralMemory from verified traps
        procedural_rules: list[ProceduralMemory] = []
        if state.status == "completed" and state.traps:
            for trap in state.traps:
                rule_id = f"proc-{session_id}-{abs(hash(trap.fingerprint)) % 1000000}"
                rule = ProceduralMemory(
                    id=rule_id,
                    content=f"Avoid {trap.fingerprint}: {trap.avoidance_rule}",
                    trigger=f"When calling tool {trap.tool_name or 'any'} with signature matching {trap.fingerprint}",
                    action=trap.avoidance_rule,
                    reasoning=f"Auto-consolidated self-healing avoidance rule from session {session_id}",
                    application="Apply proactively when invoking matching execution commands",
                    priority=2,
                    is_active=True,
                    status=MemoryStatus.ACTIVE,
                    source=RuleSource.AGENT_SELF,
                    tool_name=trap.tool_name,
                    tool_rule_priority=ToolRulePriority.NORMAL,
                    error_fingerprint=trap.fingerprint,
                    resolution_steps=[trap.avoidance_rule],
                )
                procedural_rules.append(rule)

        # 3. Persist to storage backend if memory manager is attached
        if self._memory_manager is not None:
            try:
                await self._persist_assets(task_digest, procedural_rules)
            except Exception as err:
                logger.warning("Failed to persist consolidated memory assets: %s", err)

        # 4. Clean up in-memory workbench
        LocalWorkingMemoryBlock.reset()

        logger.info(
            "Hyper consolidation completed for session %s: TaskDigest created, %d procedural rules distilled",
            session_id,
            len(procedural_rules),
        )
        return task_digest, procedural_rules

    async def _persist_assets(
        self,
        digest: TaskDigestMemory,
        rules: list[ProceduralMemory],
    ) -> None:
        """Internal helper to write consolidated memories through manager."""
        if self._memory_manager is None:
            return

        rel_store = getattr(self._memory_manager, "_relational_store", None)
        if rel_store is not None:
            # Write task digest
            if hasattr(rel_store, "save_memory"):
                await rel_store.save_memory(digest)
            for rule in rules:
                if hasattr(rel_store, "save_memory"):
                    await rel_store.save_memory(rule)


def create_consolidation_cleanup_task(
    memory_manager: MemoryManager | None = None,
) -> SessionCleanupTask:
    """Factory creating a SessionCleanupTask hook for session_post_process runner."""
    consolidator = HyperConsolidator(memory_manager=memory_manager)

    async def _cleanup_task(
        messages: Sequence[dict[str, str]],
        chat_id: str | None,
    ) -> None:
        await consolidator.consolidate_session(messages, chat_id)

    return _cleanup_task
