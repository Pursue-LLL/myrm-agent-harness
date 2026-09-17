"""Hyper Consolidation Memory Block subsystem.

[INPUT]
- context_management.working_memory.block::LocalWorkingMemoryBlock (POS: 运行时零开销手边工作台)
- toolkits.memory.types::TaskDigestMemory (POS: 结构化长程任务成果沉淀实体)
- toolkits.memory.types::ProceduralMemory (POS: 程序性经验与自愈避坑规程实体)
- toolkits.memory.types::EpisodicMemory (POS: 任务成果镜像语义向量沉淀实体)

[OUTPUT]
- HyperConsolidator: 会话终态异步巩固核心，内置 Gatekeeper 过滤平凡请求，沉淀 TaskDigest 与自愈 ProceduralMemory
- create_consolidation_cleanup_task: 异步清理与巩固后台协程工厂

[POS]
- 认知中枢终态提炼服务。将单会话手边工作台的执行经验与避坑教训资产化并持久落盘至关系与向量存储。
"""

from __future__ import annotations

import json
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
    EpisodicMemory,
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

        # 1. Persist Procedural Rules (self-healing avoidance traps)
        if rules:
            if hasattr(self._memory_manager, "store_batch"):
                try:
                    await self._memory_manager.store_batch(rules)
                except Exception as err:
                    logger.error("Failed to store procedural rules batch: %s", err)
            else:
                rel = getattr(self._memory_manager, "_relational", None)
                if rel is not None and hasattr(rel, "create_rule"):
                    for rule in rules:
                        try:
                            await rel.create_rule(rule)
                        except Exception as err:
                            logger.error("Failed to persist procedural rule %s: %s", rule.id, err)

        # 2. Persist TaskDigest as searchable EpisodicMemory
        if hasattr(self._memory_manager, "store"):
            try:
                episodic = EpisodicMemory(
                    content=digest.content or f"Task Goal: {digest.task_goal} | Status: {digest.status}",
                    source_chat_id=digest.source_session_id or None,
                    importance=0.8,
                    metadata={
                        "task_goal": str(digest.task_goal),
                        "status": str(digest.status),
                        "completed_steps": json.dumps(list(digest.completed_steps)),
                        "artifact_paths": json.dumps(list(digest.artifact_paths)),
                        "key_findings": json.dumps(list(digest.key_findings)),
                        "error_lessons": json.dumps(list(digest.error_lessons)),
                        "tool_call_count": int(digest.tool_call_count),
                        "event_type": "task_digest",
                    },
                )
                await self._memory_manager.store(episodic)
            except Exception as err:
                logger.error("Failed to persist task digest as episodic memory: %s", err)


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
