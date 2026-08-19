"""Stable integration hooks for product consumers (server, desktop).

[INPUT]
- myrm_agent_harness.agent.skill_agent.context (POS: per-agent runtime context registry)
- myrm_agent_harness.agent._internals.memory_extraction (POS: session memory extraction helpers)
- myrm_agent_harness.agent.middlewares._session_context (POS: middleware session ContextVar registry)
- myrm_agent_harness.agent.meta_tools.bash._background.registry (POS: background bash job registry)
- myrm_agent_harness.core.security.guards.privacy_tracker (POS: ContextVar privacy policy access)
- myrm_agent_harness.utils.runtime.background_job_finish_registry (POS: bash job finish hook registry)

[OUTPUT]
- Session, skill-agent context, task intent, memory telemetry（budget/injection）
  and injection contract, memory-extraction, bash-registry, background-job-finish,
  and privacy-context（policy/pseudonym-store/pseudonymizer）hook callables for server integration.

[POS]
Public re-export facade. Product code imports hooks here instead of private ``agent._*`` modules.
"""

from __future__ import annotations

from myrm_agent_harness.agent._internals.memory_extraction import (
    auto_extract_memories,
    create_extraction_llm_func,
    persist_extracted_memories,
)
from myrm_agent_harness.agent.context_management.infra.evicted import (
    EVICTED_BASENAME_PATTERN,
    build_evicted_basename,
    normalize_delivery_chat_id,
    read_evicted_line_range,
)
from myrm_agent_harness.agent.meta_tools.bash._background.job_store import (
    configure_background_job_store,
    get_background_job_store,
)
from myrm_agent_harness.agent.meta_tools.bash._background.job_store_core import (
    BackgroundJobRecord,
    map_store_status_to_shell_task_status,
)
from myrm_agent_harness.agent.meta_tools.bash._background.registry import (
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash._background.store_sync import (
    persist_terminal_state,
    persist_vault_log_ref,
)
from myrm_agent_harness.agent.meta_tools.bash._background.types import (
    INPUT_WAIT_IDLE_SECONDS,
    BackgroundProcessInfo,
)
from myrm_agent_harness.agent.middlewares._session_context import (
    get_event_logger,
    get_pseudonym_store,
    get_terminal_errors,
    set_approval_user_id,
    set_pseudonym_store,
    set_security_config,
)
from myrm_agent_harness.agent.middlewares._session_context import (
    get_workspace_root as _get_workspace_root,
)
from myrm_agent_harness.agent.middlewares._session_context import (
    set_workspace_root as _set_workspace_root,
)
from myrm_agent_harness.agent.skill_agent.context import (
    get_memory_manager,
    get_memory_runtime_budget,
    get_memory_runtime_injection,
    get_memory_runtime_injection_contract,
    get_task_intent,
    invalidate_permissions,
    set_permission_invalidation_callback,
    set_task_intent,
)
from myrm_agent_harness.agent.streaming.step_builder import build_step_data
from myrm_agent_harness.core.security.detection.pseudonym_store import (
    get_pseudonym_store as build_pseudonym_store,
)
from myrm_agent_harness.core.security.guards.privacy_tracker import (
    get_privacy_policy,
    set_privacy_policy,
)
from myrm_agent_harness.core.security.persistence.content_scan import (
    get_pii_pseudonymizer,
    set_pii_pseudonymizer,
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


def get_workspace_root() -> str:
    """Return the workspace root bound for the current async context."""
    return _get_workspace_root()


def set_workspace_root(path: str) -> None:
    """Bind the workspace root for the current async context.

    Re-exported so product code can resolve container/snapshot paths (e.g.
    ``/workspace/...``) without importing harness internals. Sets both the
    middleware-local and the cross-layer ``core.context_vars`` value.
    """
    return _set_workspace_root(path)


def install_memory_pseudonymizer(policy: object, store: object) -> object | None:
    """Install the memory-write PII pseudonymizer for a background task context.

    Uses the same closure builder as the agent-run path so regex-level S2/S3
    pseudonymization behaves identically for out-of-run persistence (e.g. memory
    extraction retries). Returns the previously installed pseudonymizer (or None)
    so the caller can restore it via :func:`restore_memory_pseudonymizer`.
    """
    from myrm_agent_harness.agent._internals.run_lifecycle import (
        _register_pii_pseudonymizer,
    )

    previous = get_pii_pseudonymizer()
    _register_pii_pseudonymizer(policy, store)
    return previous


def restore_memory_pseudonymizer(previous: object | None) -> None:
    """Restore the memory-write PII pseudonymizer captured by install."""
    set_pii_pseudonymizer(previous)


__all__ = [
    "EVICTED_BASENAME_PATTERN",
    "INPUT_WAIT_IDLE_SECONDS",
    "BackgroundJobFinishHandler",
    "BackgroundJobFinishResult",
    "BackgroundJobRecord",
    "BackgroundProcessInfo",
    "auto_extract_memories",
    "build_evicted_basename",
    "build_pseudonym_store",
    "build_step_data",
    "configure_background_job_store",
    "count_running_background_shell_jobs",
    "create_extraction_llm_func",
    "get_background_job_store",
    "get_background_registry",
    "get_event_logger",
    "get_global_background_job_finish_handler",
    "get_memory_manager",
    "get_memory_runtime_budget",
    "get_memory_runtime_injection",
    "get_memory_runtime_injection_contract",
    "get_privacy_policy",
    "get_pseudonym_store",
    "get_task_intent",
    "get_terminal_errors",
    "get_workspace_root",
    "install_memory_pseudonymizer",
    "invalidate_permissions",
    "map_store_status_to_shell_task_status",
    "normalize_delivery_chat_id",
    "persist_extracted_memories",
    "persist_terminal_state",
    "persist_vault_log_ref",
    "read_evicted_line_range",
    "restore_memory_pseudonymizer",
    "set_approval_user_id",
    "set_global_background_job_finish_handler",
    "set_permission_invalidation_callback",
    "set_privacy_policy",
    "set_pseudonym_store",
    "set_security_config",
    "set_task_intent",
    "set_workspace_root",
]
