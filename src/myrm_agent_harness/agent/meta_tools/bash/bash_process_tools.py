"""LangChain tools that operate on background bash processes.

These tools expose a thin CRUD surface over the in-process background
process registry so an LLM can list, peek at and kill background jobs it
spawned earlier via ``bash_code_execute_tool(run_in_background=True)``.

The registry is keyed by ``session_id`` to keep jobs from different chat
sessions strictly isolated; the tools always filter by the caller's
session.

[INPUT]
- agent.meta_tools.bash._background_registry::get_background_registry (POS: Background process registry singleton.)
- runtime context (POS: session_id resolution from RunnableConfig.)

[OUTPUT]
- create_bash_process_list_tool: List active/exited background processes for the current session.
- create_bash_process_output_tool: Read tail of a background process's stdout/stderr.
- create_bash_process_kill_tool: Terminate (SIGTERM / SIGKILL) a background process.

[POS]
PTC-adjacent surface tools — bash-tool-package only; no business coupling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    get_background_registry,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

_OUTPUT_DEFAULT_LINES = 100
_OUTPUT_MAX_LINES = 500

_MISSING_SESSION_PAYLOAD: dict[str, object] = {
    "content": (
        "Background process tools require a bound session_id. "
        "This protects multi-tenant isolation: a missing session_id would "
        "otherwise surface processes from other chats."
    ),
    "metadata": {"error": "missing_session_id"},
}


def _extract_session_id(config: RunnableConfig) -> str | None:
    """Return the caller's session_id or ``None`` if absent.

    Callers MUST fail-closed when this returns ``None`` to keep cross-session
    process visibility from leaking. The dedicated ``_MISSING_SESSION_PAYLOAD``
    response makes the contract explicit at every call-site.
    """
    from myrm_agent_harness.agent.context_management.context import (
        extract_context_from_runnable_config,
    )

    ctx = extract_context_from_runnable_config(config)
    sid = ctx.get("session_id")
    return str(sid) if sid else None


class _ListInput(BaseModel):
    """No inputs — list always scopes to the current session."""


def create_bash_process_list_tool() -> BaseTool:
    """List active/exited background bash jobs for the current session."""

    @tool(
        "bash_process_list_tool",
        description=(
            "List background bash processes started in this chat session. "
            "Each entry includes pid, original command, started_at, uptime_seconds, "
            "status ('running' | 'exited' | 'killed'), exit_code, error_category, "
            "and — when the job has emitted progress — last_progress "
            "(percent / step / message / updated_at). "
            "Compare last_progress across running jobs to triage stuck workers "
            "WITHOUT a per-pid bash_process_output_tool call. "
            "Use before bash_process_output_tool / bash_process_kill_tool."
        ),
        args_schema=_ListInput,
    )
    async def _list(*, config: RunnableConfig) -> dict[str, object]:
        session_id = _extract_session_id(config)
        if session_id is None:
            return _MISSING_SESSION_PAYLOAD
        registry = get_background_registry()
        items = registry.list_processes(session_id=session_id)
        return {
            "content": {
                "processes": [i.to_dict() for i in items],
                "count": len(items),
            },
            "metadata": {"session_id": session_id},
        }

    return _list


class _OutputInput(BaseModel):
    pid: int = Field(
        description="Background process pid from bash_process_list_tool",
        ge=1,
    )
    max_lines: int = Field(
        default=_OUTPUT_DEFAULT_LINES,
        description=f"Tail size per stream (1-{_OUTPUT_MAX_LINES}).",
        ge=1,
        le=_OUTPUT_MAX_LINES,
    )
    since_cursor: int | None = Field(
        default=None,
        description=(
            "Optional monotonic cursor from a previous call's ``next_cursor``. "
            "When provided, only lines emitted *after* that cursor are returned "
            "— ideal for poll loops on noisy dev servers."
        ),
    )


def create_bash_process_output_tool() -> BaseTool:
    """Return the most recent stdout/stderr tail of a background process."""

    @tool(
        "bash_process_output_tool",
        description=(
            "Read the tail of stdout/stderr from a background bash process. "
            "Pass ``since_cursor`` (from a previous response's ``next_cursor``) "
            "to fetch only new lines and keep tokens cheap when polling dev "
            "servers / long crawlers."
        ),
        args_schema=_OutputInput,
    )
    async def _output(
        pid: int,
        max_lines: int = _OUTPUT_DEFAULT_LINES,
        since_cursor: int | None = None,
        *,
        config: RunnableConfig,
    ) -> dict[str, object]:
        session_id = _extract_session_id(config)
        if session_id is None:
            return _MISSING_SESSION_PAYLOAD
        registry = get_background_registry()
        info = registry.get(pid)
        if info is None or info.session_id != session_id:
            return {
                "content": f"No background process with pid={pid} in this session.",
                "metadata": {"pid": pid, "found": False},
            }
        streams = registry.get_output(pid, max_lines=max_lines, since_cursor=since_cursor)
        return {
            "content": {
                "pid": pid,
                "status": info.status,
                "exit_code": info.exit_code,
                "stdout": streams["stdout"],
                "stderr": streams["stderr"],
                "next_cursor": streams["next_cursor"],
                "dropped": streams["dropped"],
            },
            "metadata": {"pid": pid, "session_id": session_id},
        }

    return _output


class _KillInput(BaseModel):
    pid: int = Field(description="Background process pid to terminate", ge=1)
    force: bool = Field(
        default=False,
        description="If True send SIGKILL immediately, else SIGTERM (graceful).",
    )


def create_bash_process_kill_tool() -> BaseTool:
    """Terminate (or force-kill) a background process for the current session."""

    @tool(
        "bash_process_kill_tool",
        description=(
            "Stop a background bash process by pid. Prefer force=False "
            "(SIGTERM) first so the process can clean up; pass force=True "
            "only after SIGTERM hangs."
        ),
        args_schema=_KillInput,
    )
    async def _kill(
        pid: int,
        force: bool = False,
        *,
        config: RunnableConfig,
    ) -> dict[str, object]:
        session_id = _extract_session_id(config)
        if session_id is None:
            return _MISSING_SESSION_PAYLOAD
        registry = get_background_registry()
        info = registry.get(pid)
        if info is None or info.session_id != session_id:
            return {
                "content": f"No background process with pid={pid} in this session.",
                "metadata": {"pid": pid, "found": False},
            }
        ok = await registry.kill(pid, force=force)
        return {
            "content": (
                f"Sent {'SIGKILL' if force else 'SIGTERM'} to pid={pid}" if ok else f"Failed to signal pid={pid}"
            ),
            "metadata": {
                "pid": pid,
                "force": force,
                "killed": ok,
                "session_id": session_id,
            },
        }

    return _kill


__all__ = [
    "create_bash_process_kill_tool",
    "create_bash_process_list_tool",
    "create_bash_process_output_tool",
]
