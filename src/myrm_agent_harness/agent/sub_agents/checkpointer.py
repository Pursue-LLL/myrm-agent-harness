"""Shared in-memory checkpointer for subagents.

[INPUT]
- langgraph.checkpoint.memory::InMemorySaver (POS: LangGraph in-memory checkpoint backend)

[OUTPUT]
- get_subagent_checkpointer: shared InMemorySaver singleton for all subagent threads
- delete_subagent_checkpoint: drop a finished subagent thread (memory hygiene)

[POS]
HITL approval for subagents requires a configured checkpointer (approval/middleware.py
requires it so GraphInterrupt state survives the child run). Each subagent uses
thread_id == task_id (set via context["approval_session_key"]), so one shared
InMemorySaver instance keeps threads isolated per subagent and lets a resume pass
(Command(resume=...)) restore the interrupted graph from the same thread.

The shared saver is intentionally NOT the parent agent's checkpointer: subagent
message history stays in its own thread and never pollutes the parent thread
(see SUB_AGENT_SYSTEM.md §7).

Memory hygiene: delete_subagent_checkpoint() drops the thread once a subagent
reaches a terminal (non-approval) status. PENDING_APPROVAL threads are kept so
the resume pass can restore them.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

_checkpointer_lock = asyncio.Lock()
_subagent_checkpointer: InMemorySaver | None = None


def get_subagent_checkpointer() -> InMemorySaver:
    """Return the process-wide shared InMemorySaver for subagent threads.

    Lazy singleton: created on first use so importing the sub_agents package
    never allocates a checkpointer (test suites and headless tools benefit).
    """
    global _subagent_checkpointer
    if _subagent_checkpointer is None:
        _subagent_checkpointer = InMemorySaver()
    return _subagent_checkpointer


async def delete_subagent_checkpoint(thread_id: str) -> None:
    """Drop a finished subagent thread from the shared checkpointer.

    Called by the subagent executor once a run reaches a terminal status that is
    not PENDING_APPROVAL (approval threads must survive for the resume pass).
    Safe to call for unknown thread ids (no-op).
    """
    saver = _subagent_checkpointer
    if saver is None:
        return
    try:
        async with _checkpointer_lock:
            await saver.adelete_thread(thread_id)
    except Exception:
        # Deletion is best-effort hygiene; never break the executor for it.
        pass


async def _drop_finished_subagent_thread(task_id: str, status: Any) -> None:
    """Internal helper: delete thread for terminal non-approval statuses."""
    from myrm_agent_harness.agent.sub_agents.types import SubAgentStatus

    if status is SubAgentStatus.PENDING_APPROVAL or status == "pending_approval":
        return
    await delete_subagent_checkpoint(task_id)
