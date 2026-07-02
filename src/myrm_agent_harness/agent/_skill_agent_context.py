"""SkillAgent ContextVar management and background task utilities.

[INPUT]
- skills::SkillMetadata (POS: Skill metadata type)
- toolkits.memory.manager::MemoryManager (POS: Memory manager)
- toolkits.storage.base::StorageProvider (POS: Storage provider)

[OUTPUT]
- ContextVar getters/setters for storage_backend, memory_manager, loaded_skills, task_intent
- Permission invalidation callback management
- Background task tracking and graceful shutdown

[POS]
Module-level ContextVar management and background task utilities.
Used by SkillAgent and middlewares for cross-cutting session state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.skills import SkillMetadata
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = get_agent_logger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()

_storage_backend_var: ContextVar[StorageProvider | None] = ContextVar("storage_backend", default=None)
_memory_manager_var: ContextVar[MemoryManager | None] = ContextVar("memory_manager", default=None)
_loaded_skills_var: ContextVar[list[SkillMetadata] | None] = ContextVar("loaded_skills", default=None)
_permission_invalidation_callback: ContextVar[Callable[[str, str], None] | None] = ContextVar(
    "permission_invalidation_callback", default=None
)
_task_intent_var: ContextVar[str] = ContextVar("task_intent", default="")


async def wait_all_background_tasks(timeout_seconds: float = 30.0) -> None:
    """Wait for all background tasks to complete (for graceful shutdown).

    Called by Server business layer on SIGTERM to ensure background tasks
    (memory extraction, skill review, etc.) are not lost.

    Args:
        timeout_seconds: Maximum wait time (default 30s), force-returns on timeout.

    Example:
        # In Server main.py (SIGTERM handler):
        from myrm_agent_harness.agent.skill_agent import wait_all_background_tasks
        await wait_all_background_tasks(timeout_seconds=30)
    """
    if not _background_tasks:
        return

    logger.warning(
        "Waiting for %d background tasks to complete (timeout=%ds)",
        len(_background_tasks),
        timeout_seconds,
    )

    try:
        await asyncio.wait_for(
            asyncio.gather(*list(_background_tasks), return_exceptions=True),
            timeout=timeout_seconds,
        )
        logger.info("All background tasks completed gracefully")
    except TimeoutError:
        logger.warning(
            "Timeout reached, %d tasks still pending (forced shutdown)",
            len(_background_tasks),
        )
    except Exception as e:
        logger.error("Error waiting for background tasks: %s", e, exc_info=True)


def track_background_task(task: asyncio.Task[None]) -> None:
    """Register a background task for graceful shutdown tracking."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def get_storage_backend() -> StorageProvider | None:
    """Get the current storage backend from ContextVar."""
    return _storage_backend_var.get()


def set_storage_backend(backend: StorageProvider | None) -> None:
    """Set the current storage backend in ContextVar."""
    _storage_backend_var.set(backend)


def get_memory_manager() -> MemoryManager | None:
    """Get the current memory manager from ContextVar."""
    return _memory_manager_var.get()


def set_memory_manager(manager: MemoryManager | None) -> None:
    """Set the current memory manager in ContextVar."""
    _memory_manager_var.set(manager)


def get_loaded_skills() -> list[SkillMetadata]:
    """Get the list of skills loaded during the current session."""
    return _loaded_skills_var.get() or []


def add_loaded_skill(skill: SkillMetadata) -> None:
    """Record a skill loaded during the current session (for trust attenuation)."""
    current = get_loaded_skills()
    _loaded_skills_var.set([*current, skill])


def reset_loaded_skills() -> None:
    """Clear loaded skills at session end."""
    _loaded_skills_var.set([])


def get_task_intent() -> str:
    """Get the current task intent from ContextVar."""
    return _task_intent_var.get()


def set_task_intent(intent: str) -> None:
    """Set the current task intent in ContextVar."""
    _task_intent_var.set(intent)


def set_permission_invalidation_callback(
    callback: Callable[[str, str], None] | None,
) -> None:
    """Register permission invalidation callback (called by business layer).

    The callback is invoked when permissions are revoked, allowing business
    layer to clear cached permissions.

    Args:
        callback: Function that takes (user_id, skill_id) and clears cache.
                  Set to None to unregister.

    Example:
        set_permission_invalidation_callback(my_clear_cache_fn)
    """
    _permission_invalidation_callback.set(callback)


def invalidate_permissions(user_id: str, skill_id: str) -> None:
    """Notify Agent to clear permission cache (framework-layer API).

    Business layer calls this after revoking permissions. The registered
    callback (if any) is invoked to clear cached permissions.

    Args:
        user_id: User ID whose permissions were revoked
        skill_id: Skill ID whose permissions were revoked

    Example:
        # In business layer revoke API:
        await revoke_permissions(...)
        invalidate_permissions(user_id, skill_id)  # Notify framework
    """
    callback = _permission_invalidation_callback.get()
    if callback:
        try:
            callback(user_id, skill_id)
            logger.info("Permission cache invalidated: user=%s, skill=%s", user_id, skill_id)
        except Exception as e:
            logger.error(
                "Failed to invalidate permission cache: user=%s, skill=%s, error=%s",
                user_id,
                skill_id,
                e,
            )
    else:
        logger.warning(
            "Permission invalidation callback not registered, "
            "cache for skill %s may be stale. Consider calling "
            "set_permission_invalidation_callback() during Agent initialization.",
            skill_id,
        )


class SkillAgentContextMixin:
    """Context preparation mixin for SkillAgent."""

    async def _prepare_context(self, context: dict[str, object]) -> dict[str, object]:
        """Prepare context — ContextVar for non-serializable session objects."""
        context = await super()._prepare_context(context)  # type: ignore[misc]

        set_storage_backend(self.storage_backend)  # type: ignore[attr-defined]
        set_memory_manager(self.memory_manager)  # type: ignore[attr-defined]

        skill_paths = await self._get_skill_storage_paths()  # type: ignore[attr-defined]
        if skill_paths:
            context["skill_paths"] = skill_paths

        return context
