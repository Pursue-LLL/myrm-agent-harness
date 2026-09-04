"""ContextVar recovery for LangGraph ToolNode execution.

[INPUT]
- toolkits.code_execution.executors.base::get_executor (POS: ContextVar accessor)
- toolkits.code_execution.executors.base::get_stashed_executor (POS: Session-keyed fallback)
- toolkits.code_execution.executors.base::set_executor (POS: ContextVar setter)
- agent.context_management.context::extract_context_from_runnable_config (POS: Config→context extractor)

[OUTPUT]
- ensure_executor: Acquire executor with session-stash fallback for ToolNode context loss.
- restore_context_vars: Restore all ContextVars from context dict + executor.

[POS]
When LangGraph ToolNode runs tools in a different asyncio task or after interrupt/resume,
ContextVars bound during setup_workspace may be absent. This module provides a self-healing
fallback that recovers the executor from the session stash (a process-level dict keyed by
session_id) and re-binds all context vars.

Normal-path cost: one `_executor_var.get()` — no fallback overhead when ContextVar is present.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.runnables.config import RunnableConfig

    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)


def restore_context_vars(context: dict[str, object], executor: object) -> None:
    """Restore ContextVars that may be lost when LangGraph executes tool nodes.

    Restores: executor, workspace_root, chat_id, workspace_storage_fs_root.
    """
    from myrm_agent_harness.agent.context_management.infra.evicted.content import (
        normalize_delivery_chat_id,
    )
    from myrm_agent_harness.agent.middlewares.approval import set_workspace_root
    from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var
    from myrm_agent_harness.toolkits.code_execution.executors.base import set_executor
    from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
        _workspace_storage_fs_root,
        bind_workspace_storage_root,
    )

    set_executor(executor)  # type: ignore[arg-type]

    workspace_path = context.get("workspace_path")
    if workspace_path:
        set_workspace_root(str(workspace_path))
        workspace_root_var.set(str(workspace_path))

    delivery_chat_id = str(context.get("chat_id") or "").strip()
    if not delivery_chat_id:
        session_id = str(context.get("session_id") or context.get("approval_session_key") or "")
        delivery_chat_id = normalize_delivery_chat_id(session_id)
    if delivery_chat_id:
        chat_id_var.set(delivery_chat_id)

    message_id = str(context.get("message_id") or "").strip()
    if message_id:
        from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
            set_current_message_id,
        )

        set_current_message_id(message_id)

    if _workspace_storage_fs_root.get() is None:
        ws_root = context.get("workspaces_storage_root")
        if ws_root:
            bind_workspace_storage_root(Path(str(ws_root)))


def ensure_executor(config: RunnableConfig) -> CodeExecutor:
    """Acquire a CodeExecutor, falling back to session stash if ContextVar is lost.

    Resolution order:
    1. ContextVar direct (normal path, zero overhead).
    2. Session stash recovery (LangGraph ToolNode context-loss scenario).
    3. RuntimeError with diagnostic message.
    """
    from myrm_agent_harness.agent.context_management.context import (
        extract_context_from_runnable_config,
    )
    from myrm_agent_harness.toolkits.code_execution.executors.base import (
        get_executor,
        get_stashed_executor,
    )

    executor = get_executor()
    if executor is not None:
        return executor

    context = extract_context_from_runnable_config(config)
    session_id = str(context.get("session_id", "")) or None

    if session_id:
        stashed = get_stashed_executor(session_id)
        if stashed is not None:
            logger.info(
                "ContextVar executor lost; recovered from session stash (session=%s)",
                session_id,
            )
            restore_context_vars(context, stashed)
            return stashed

    raise RuntimeError(
        "CodeExecutor not available. "
        "Neither ContextVar nor session stash has a valid executor. "
        "Ensure setup_workspace() was called in the current run lifecycle."
    )
