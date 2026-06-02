"""Idle worker integration for skill synchronization.

Registers skill_sync as a background idle task type, leveraging the existing
IdleTaskRegistry and GlobalAdaptiveScheduler infrastructure.

[INPUT]
- .manager::SkillSyncManager
- agent.background_worker.idle_tasks::register_idle_task_handler

[OUTPUT]
- register_skill_sync_idle_handler: Registers sync as idle task type.
- SKILL_SYNC_TASK_TYPE: Task type constant.

[POS]
Bridges skill sync into the idle worker system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord

logger = logging.getLogger(__name__)

SKILL_SYNC_TASK_TYPE = "skill_sync"

_sync_manager_ref: object | None = None


def register_skill_sync_idle_handler(sync_manager: object) -> None:
    """Register skill sync as an idle task handler.

    Call this during system initialization after SkillSyncManager is created.

    Args:
        sync_manager: SkillSyncManager instance.
    """
    global _sync_manager_ref
    _sync_manager_ref = sync_manager

    from myrm_agent_harness.agent.background_worker.idle_tasks import (
        register_idle_task_handler,
    )

    register_idle_task_handler(SKILL_SYNC_TASK_TYPE, _handle_skill_sync)
    logger.info("Skill sync idle handler registered")


async def _handle_skill_sync(task: IdleTaskRecord, session_id: str) -> dict[str, object]:
    """Handle skill_sync idle task.

    Performs a full bidirectional sync (pull then push).
    """
    from .manager import SkillSyncManager

    if not isinstance(_sync_manager_ref, SkillSyncManager):
        logger.warning("SkillSyncManager not available, skipping sync task")
        return {"skipped": True, "reason": "No SkillSyncManager"}

    manager: SkillSyncManager = _sync_manager_ref

    if manager.is_syncing:
        return {"skipped": True, "reason": "Sync already in progress"}

    push_result, pull_result = await manager.full_sync()

    return {
        "push_success": push_result.success,
        "push_count": push_result.pushed_count,
        "pull_success": pull_result.success,
        "pull_new": pull_result.new_count,
        "pull_updated": pull_result.updated_count,
    }
