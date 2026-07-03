"""Unified LangChain tool for background bash process management.

Single ``bash_process_tool`` with ``action=list|output|kill`` replaces three
separate list/output/kill tools. Operates on the in-process background
process registry for jobs spawned via ``bash_code_execute_tool(run_in_background=True)``.

[INPUT]
- agent.meta_tools.bash._background_registry::get_background_registry (POS: registry singleton)
- runtime context (POS: session_id from RunnableConfig)

[OUTPUT]
- create_bash_process_tool: Unified process management tool factory
- BASH_PROCESS_TOOL_NAME: Stable tool id for deferred activation

[POS]
PTC-adjacent surface tool — bash-tool-package only; no business coupling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    get_background_registry,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

BASH_PROCESS_TOOL_NAME = "bash_process_tool"

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
    from myrm_agent_harness.agent.context_management.context import (
        extract_context_from_runnable_config,
    )

    ctx = extract_context_from_runnable_config(config)
    sid = ctx.get("session_id")
    return str(sid) if sid else None


class _BashProcessInput(BaseModel):
    action: Literal["list", "output", "kill"] = Field(
        description=(
            "list: all background jobs in this session (includes last_progress when available); "
            "output: tail stdout/stderr for pid; kill: stop pid (SIGTERM unless force=true)."
        ),
    )
    pid: int | None = Field(
        default=None,
        description="Required for output and kill. Background process pid from list or spawn metadata.",
        ge=1,
    )
    max_lines: int = Field(
        default=_OUTPUT_DEFAULT_LINES,
        description=f"For output: tail size per stream (1-{_OUTPUT_MAX_LINES}).",
        ge=1,
        le=_OUTPUT_MAX_LINES,
    )
    since_cursor: int | None = Field(
        default=None,
        description=(
            "For output: monotonic cursor from a previous next_cursor for incremental polling."
        ),
    )
    force: bool = Field(
        default=False,
        description="For kill: send SIGKILL when true, else SIGTERM first.",
    )


async def _handle_list(session_id: str) -> dict[str, object]:
    registry = get_background_registry()
    items = registry.list_processes(session_id=session_id)
    return {
        "content": {
            "processes": [i.to_dict() for i in items],
            "count": len(items),
        },
        "metadata": {"session_id": session_id, "action": "list"},
    }


async def _handle_output(
    session_id: str,
    pid: int,
    max_lines: int,
    since_cursor: int | None,
) -> dict[str, object]:
    registry = get_background_registry()
    info = registry.get(pid)
    if info is None or info.session_id != session_id:
        return {
            "content": f"No background process with pid={pid} in this session.",
            "metadata": {"pid": pid, "found": False, "action": "output"},
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
        "metadata": {"pid": pid, "session_id": session_id, "action": "output"},
    }


async def _handle_kill(session_id: str, pid: int, force: bool) -> dict[str, object]:
    registry = get_background_registry()
    info = registry.get(pid)
    if info is None or info.session_id != session_id:
        return {
            "content": f"No background process with pid={pid} in this session.",
            "metadata": {"pid": pid, "found": False, "action": "kill"},
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
            "action": "kill",
        },
    }


def create_bash_process_tool() -> BaseTool:
    """Return the unified background process management tool."""

    @tool(
        BASH_PROCESS_TOOL_NAME,
        description=(
            "Manage background bash processes started with bash_code_execute_tool(run_in_background=true). "
            "Actions: list (session jobs + last_progress), output (tail/ incremental poll via since_cursor), "
            "kill (SIGTERM or force SIGKILL)."
        ),
        args_schema=_BashProcessInput,
    )
    async def _bash_process(
        action: Literal["list", "output", "kill"],
        pid: int | None = None,
        max_lines: int = _OUTPUT_DEFAULT_LINES,
        since_cursor: int | None = None,
        force: bool = False,
        *,
        config: RunnableConfig,
    ) -> dict[str, object]:
        session_id = _extract_session_id(config)
        if session_id is None:
            return _MISSING_SESSION_PAYLOAD

        if action == "list":
            return await _handle_list(session_id)
        if action in {"output", "kill"} and pid is None:
            return {
                "content": f"action={action!r} requires pid.",
                "metadata": {"error": "missing_pid", "action": action},
            }
        if action == "output":
            assert pid is not None
            return await _handle_output(session_id, pid, max_lines, since_cursor)
        if action == "kill":
            assert pid is not None
            return await _handle_kill(session_id, pid, force)

        return {
            "content": f"Unknown action: {action!r}. Use list, output, or kill.",
            "metadata": {"error": "invalid_action"},
        }

    return _bash_process


__all__ = [
    "BASH_PROCESS_TOOL_NAME",
    "create_bash_process_tool",
]
