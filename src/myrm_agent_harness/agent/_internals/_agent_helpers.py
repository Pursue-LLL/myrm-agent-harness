"""Agent runtime helper functions.

Per-run guard resets, query text extraction, idle task scheduling,
usage ledger initialization.

[INPUT]
- agent.middlewares (POS: guard/state reset functions)
- agent.security (POS: security guard reset functions)
- agent.background_worker (POS: idle task scheduling)
- utils.token_economics (POS: UsageLedger)

[OUTPUT]
- reset_all_guards: Reset all per-request guard state before a new agent run.
- extract_query_text: Extract human-readable query string from various input types.
- schedule_post_run_idle_tasks: Enqueue background idle tasks after a successful agent run.
- init_usage_ledger: Attach a UsageLedger to the current request scope.

[POS]
Agent runtime helper functions — guard resets, query extraction, idle tasks, usage ledger.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_economics.tracker import set_usage_ledger

logger = get_agent_logger(__name__)

__all__ = [
    "extract_query_text",
    "init_usage_ledger",
    "reset_all_guards",
    "schedule_post_run_idle_tasks",
]

_background_tasks: set[asyncio.Task[None]] = set()


def _fire_and_forget(coro: Coroutine[object, object, object]) -> None:
    """Schedule a coroutine as a background task without risk of GC collection."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def reset_all_guards(*, is_resume: bool = False, graph_recursion_limit: int = 100) -> None:
    """Reset all per-request guard state before a new agent run.

    Args:
        is_resume: When ``True`` (approval-resume flow), preserve error
            signature counters in LoopGuard so that cross-resume loops
            are still detected.
        graph_recursion_limit: LangGraph recursion limit, forwarded to
            LoopGuard for dynamic budget threshold calculation.
    """
    from myrm_agent_harness.agent.middlewares._session_context import (
        reset_terminal_errors,
    )
    from myrm_agent_harness.agent.middlewares.approval import reset_denial_counter
    from myrm_agent_harness.agent.middlewares.completion_guard import (
        reset_completion_guard,
    )
    from myrm_agent_harness.agent.middlewares.plan_confirm_middleware import (
        reset_plan_confirm_state,
    )
    from myrm_agent_harness.agent.middlewares.replan_middleware import (
        reset_replan_attempts,
    )
    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
        reset_loop_guard,
    )
    from myrm_agent_harness.agent.security.audit import reset_audit_log
    from myrm_agent_harness.agent.security.guards.frequency_guard import (
        reset_frequency_guard,
    )
    from myrm_agent_harness.agent.security.guards.privacy_tracker import (
        reset_privacy_tracker,
    )
    from myrm_agent_harness.agent.security.guards.taint_tracker import (
        reset_taint_tracker,
    )

    reset_loop_guard(
        is_resume=is_resume,
        graph_recursion_limit=graph_recursion_limit,
    )
    reset_frequency_guard()
    reset_replan_attempts()
    reset_plan_confirm_state()
    reset_terminal_errors()
    reset_denial_counter()
    reset_completion_guard()
    reset_taint_tracker()
    reset_audit_log()
    reset_privacy_tracker()


def extract_query_text(query: object) -> str:
    """Extract a human-readable query string from various input types."""
    from langgraph.types import Command

    if isinstance(query, Command):
        return f"Resume: {query.resume if hasattr(query, 'resume') else 'unknown'}"
    if isinstance(query, str):
        return query
    if isinstance(query, list):
        return next(
            (p.get("text", "") for p in query if isinstance(p, dict) and p.get("type") == "text"),
            "",
        )
    return str(query)


def schedule_post_run_idle_tasks(merged_context: dict[str, object]) -> None:
    """Enqueue background idle tasks after a successful agent run."""
    session_id = str(merged_context.get("session_id", ""))
    workspace_root = str(merged_context.get("workspace_root", ""))
    user_id = str(merged_context.get("user_id", "system"))

    if not (session_id and workspace_root):
        return

    from myrm_agent_harness.agent.background_worker.idle_tasks import (
        default_idle_callback,
    )
    from myrm_agent_harness.agent.background_worker.idle_worker import (
        schedule_idle_task,
    )
    from myrm_agent_harness.agent.background_worker.registry import (
        get_idle_task_registry,
    )

    registry = get_idle_task_registry(workspace_root)
    try:
        chat_id = str(merged_context.get("chat_id", ""))

        # Serialize recent messages for cognitive_derivation with Token-Aware Window
        raw_messages = merged_context.get("messages", [])
        serialized_msgs = []
        if isinstance(raw_messages, list):
            from langchain_core.messages import BaseMessage

            # Simple length-based safety valve (approx 4 chars per token)
            # Limit to ~4000 tokens => 16000 chars total
            MAX_CHARS = 16000
            current_chars = 0

            for m in reversed(raw_messages):
                role = ""
                content = ""
                if isinstance(m, BaseMessage):
                    role = m.type
                    content = str(m.content)
                elif isinstance(m, dict):
                    role = m.get("role", "")
                    content = str(m.get("content", ""))

                if not content:
                    continue

                msg_len = len(content)
                if current_chars + msg_len > MAX_CHARS:
                    # Truncate to fit the remaining budget safely
                    remaining = MAX_CHARS - current_chars
                    if remaining > 200:
                        truncated_content = content[:remaining] + "...[TRUNCATED]"
                        serialized_msgs.insert(0, {"role": role, "content": truncated_content})
                        current_chars += len(truncated_content)
                    break

                serialized_msgs.insert(0, {"role": role, "content": content})
                current_chars += msg_len

        _fire_and_forget(registry.enqueue(session_id, user_id, "cognitive_consolidation", {}))
        if chat_id and serialized_msgs:
            _fire_and_forget(
                registry.enqueue(
                    session_id,
                    user_id,
                    "cognitive_derivation",
                    {
                        "chat_id": chat_id,
                        "messages": serialized_msgs[-20:],  # Only need recent context
                    },
                )
            )
            # Add trace analysis for skill extraction (CAPTURED evolution)
            from myrm_agent_harness.agent.middlewares._session_context import get_event_logger

            event_logger = get_event_logger()
            if event_logger and event_logger._backend:
                _fire_and_forget(
                    registry.enqueue(
                        session_id,
                        user_id,
                        "session_evidence_extraction",
                        {"chat_id": chat_id, "agent_id": str(merged_context.get("agent_id", "default"))},
                    )
                )

        if chat_id:
            _fire_and_forget(registry.enqueue(session_id, user_id, "context_compaction", {"chat_id": chat_id}))
        schedule_idle_task(
            session_id,
            lambda: default_idle_callback(session_id, registry),
            delay_seconds=60,
        )
    except Exception as exc:
        logger.error("Failed to schedule idle task for %s: %s", session_id, exc)


def init_usage_ledger(context: dict[str, object] | None) -> None:
    """Attach a ``UsageLedger`` to the current request scope."""
    if not context:
        return
    workspace_path = context.get("workspace_path")
    if not workspace_path:
        return
    try:
        from pathlib import Path

        from myrm_agent_harness.utils.token_economics.usage_ledger import UsageLedger

        session_dir = Path(str(workspace_path))
        set_usage_ledger(UsageLedger(session_dir=session_dir))
    except Exception:
        logger.debug("Failed to initialize UsageLedger", exc_info=True)
