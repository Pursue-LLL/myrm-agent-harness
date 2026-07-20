"""Stable integration hooks for product consumers (server, desktop).

[INPUT]
- myrm_agent_harness.agent._skill_agent_context (POS: per-agent runtime context registry)
- myrm_agent_harness.agent._internals.memory_extraction (POS: session memory extraction helpers)
- myrm_agent_harness.agent.middlewares._session_context (POS: middleware session ContextVar registry)
- myrm_agent_harness.agent.meta_tools.bash._background_registry (POS: background bash job registry)
- myrm_agent_harness.utils.runtime.background_job_finish_registry (POS: bash job finish hook registry)

[OUTPUT]
- Session, skill-agent context, task intent, memory telemetry（budget/injection）
  and injection contract, memory-extraction, bash-registry, and background-job-finish
  hook callables for server integration.

[POS]
Public re-export facade. Product code imports hooks here instead of private ``agent._*`` modules.
"""

from __future__ import annotations

from myrm_agent_harness.agent._internals.memory_extraction import (
    create_extraction_llm_func,
    persist_extracted_memories,
)
from myrm_agent_harness.agent._skill_agent_context import (
    get_memory_manager,
    get_memory_runtime_budget,
    get_memory_runtime_injection_contract,
    get_memory_runtime_injection,
    get_task_intent,
    invalidate_permissions,
    set_permission_invalidation_callback,
    set_task_intent,
)
from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash._background_job_store import (
    configure_background_job_store,
    get_background_job_store,
)
from myrm_agent_harness.agent.meta_tools.bash._background_job_store_core import (
    BackgroundJobRecord,
    map_store_status_to_shell_task_status,
)
from myrm_agent_harness.agent.meta_tools.bash._background_types import BackgroundProcessInfo
from myrm_agent_harness.agent.middlewares._session_context import (
    get_event_logger,
    get_terminal_errors,
    set_approval_user_id,
)
from myrm_agent_harness.utils.runtime.background_job_finish_registry import (
    BackgroundJobFinishHandler,
    BackgroundJobFinishResult,
    get_global_background_job_finish_handler,
    set_global_background_job_finish_handler,
)


def count_running_background_shell_jobs(session_id: str | None = None) -> int:
    """Return the number of running harness background shell jobs."""
    return get_background_registry().count_running(session_id)


__all__ = [
    "BackgroundJobFinishHandler",
    "BackgroundJobFinishResult",
    "BackgroundJobRecord",
    "BackgroundProcessInfo",
    "configure_background_job_store",
    "count_running_background_shell_jobs",
    "create_extraction_llm_func",
    "get_background_job_store",
    "get_background_registry",
    "get_event_logger",
    "get_global_background_job_finish_handler",
    "get_memory_manager",
    "get_memory_runtime_budget",
    "get_memory_runtime_injection_contract",
    "get_memory_runtime_injection",
    "get_task_intent",
    "get_terminal_errors",
    "invalidate_permissions",
    "map_store_status_to_shell_task_status",
    "persist_extracted_memories",
    "set_approval_user_id",
    "set_global_background_job_finish_handler",
    "set_permission_invalidation_callback",
    "set_task_intent",
]
