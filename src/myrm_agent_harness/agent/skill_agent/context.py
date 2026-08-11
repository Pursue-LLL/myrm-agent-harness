"""SkillAgent ContextVar management and background task utilities.

[INPUT]
- skills::SkillMetadata (POS: Skill metadata type)
- toolkits.memory.manager::MemoryManager (POS: Memory manager)
- toolkits.storage.base::StorageProvider (POS: Storage provider)

[OUTPUT]
- ContextVar getters/setters for storage_backend, memory_manager, loaded_skills (get/add/set/reset), task_intent
- ContextVar getters/setters for memory runtime telemetry (budget + injection)
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
from typing import TYPE_CHECKING, Literal, TypedDict

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
_memory_runtime_budget_var: ContextVar[MemoryRuntimeBudget | None] = ContextVar(
    "memory_runtime_budget",
    default=None,
)
_memory_runtime_injection_var: ContextVar[MemoryRuntimeInjection | None] = ContextVar(
    "memory_runtime_injection",
    default=None,
)
_permission_invalidation_callback: ContextVar[Callable[[str, str], None] | None] = ContextVar(
    "permission_invalidation_callback", default=None
)
_task_intent_var: ContextVar[str] = ContextVar("task_intent", default="")


class MemoryRuntimeBudget(TypedDict):
    used: int
    total: int


MemoryInjectionState = Literal["applied", "not_applied"]
MemoryInjectionSource = Literal["snapshot", "fallback"]
MemoryInjectionReason = Literal[
    "missing_context",
    "not_injected",
    "recall_mode_tools",
    "load_error",
    "static_error",
    "invalid_static_payload",
    "empty_context",
    "already_present",
]


class MemoryRuntimeInjection(TypedDict, total=False):
    state: MemoryInjectionState
    source: MemoryInjectionSource
    reason: MemoryInjectionReason


MEMORY_RUNTIME_INJECTION_STATES: tuple[MemoryInjectionState, ...] = (
    "applied",
    "not_applied",
)
MEMORY_RUNTIME_INJECTION_SOURCES: tuple[MemoryInjectionSource, ...] = (
    "snapshot",
    "fallback",
)
MEMORY_RUNTIME_INJECTION_REASONS: tuple[MemoryInjectionReason, ...] = (
    "missing_context",
    "not_injected",
    "recall_mode_tools",
    "load_error",
    "static_error",
    "invalid_static_payload",
    "empty_context",
    "already_present",
)
_NOT_APPLIED_REASONS: set[MemoryInjectionReason] = set(MEMORY_RUNTIME_INJECTION_REASONS)


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


def get_memory_runtime_budget() -> MemoryRuntimeBudget | None:
    """Get memory budget telemetry emitted by memory context middleware."""
    payload = _memory_runtime_budget_var.get()
    if payload is None:
        return None
    return {"used": payload["used"], "total": payload["total"]}


def set_memory_runtime_budget(payload: MemoryRuntimeBudget | None) -> None:
    """Set memory budget telemetry for server-side SSE/persistence hooks."""
    if payload is None:
        _memory_runtime_budget_var.set(None)
        return
    _memory_runtime_budget_var.set(
        {
            "used": max(0, int(payload["used"])),
            "total": max(0, int(payload["total"])),
        }
    )


def get_memory_runtime_injection() -> MemoryRuntimeInjection | None:
    """Get memory injection telemetry emitted by memory context middleware."""
    payload = _memory_runtime_injection_var.get()
    if payload is None:
        return None
    copied: MemoryRuntimeInjection = {"state": payload["state"]}
    if "source" in payload:
        copied["source"] = payload["source"]
    if "reason" in payload:
        copied["reason"] = payload["reason"]
    return copied


def set_memory_runtime_injection(payload: MemoryRuntimeInjection | None) -> None:
    """Set normalized memory injection telemetry for server consumption."""
    if payload is None:
        _memory_runtime_injection_var.set(None)
        return

    state = payload.get("state")
    if state == "applied":
        normalized: MemoryRuntimeInjection = {"state": "applied"}
        source = payload.get("source")
        if source in MEMORY_RUNTIME_INJECTION_SOURCES:
            normalized["source"] = source
        _memory_runtime_injection_var.set(normalized)
        return

    if state == "not_applied":
        normalized = {"state": "not_applied"}
        reason = payload.get("reason")
        if reason in _NOT_APPLIED_REASONS:
            normalized["reason"] = reason
        _memory_runtime_injection_var.set(normalized)
        return

    _memory_runtime_injection_var.set(None)


def get_memory_runtime_injection_contract() -> dict[str, tuple[str, ...]]:
    """Expose stable runtime injection contract for cross-layer parity checks."""
    return {
        "states": MEMORY_RUNTIME_INJECTION_STATES,
        "sources": MEMORY_RUNTIME_INJECTION_SOURCES,
        "reasons": MEMORY_RUNTIME_INJECTION_REASONS,
    }


def get_loaded_skills() -> list[SkillMetadata]:
    """Get the list of skills loaded during the current session."""
    return _loaded_skills_var.get() or []


def add_loaded_skill(skill: SkillMetadata) -> None:
    """Record a skill loaded during the current session (for trust attenuation)."""
    current = get_loaded_skills()
    _loaded_skills_var.set([*current, skill])


def set_loaded_skills(skills: list[SkillMetadata]) -> None:
    """Replace the loaded-skills list (used when rehydrating from chat history)."""
    _loaded_skills_var.set(list(skills))


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
