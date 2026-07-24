"""Unified LangChain tool for background bash process management.

Single ``bash_process_tool`` manages list/output/wait/kill/stdin for jobs spawned
via ``bash_code_execute_tool(run_in_background=True)``.

[INPUT]
- agent.meta_tools.bash._background_registry::get_background_registry (POS: registry singleton)
- runtime context (POS: session_id from RunnableConfig)

[OUTPUT]
- create_bash_process_tool: Unified process management tool factory
- BASH_PROCESS_TOOL_NAME: Stable tool id for spawn lifecycle tracking

[POS]
PTC-adjacent surface tool — bash-tool-package only; no business coupling.
"""

from __future__ import annotations

import re
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
_WAIT_DEFAULT_SECONDS = 30
_WAIT_MAX_SECONDS = 120

_BASH_PROCESS_ACTIONS = Literal[
    "list",
    "output",
    "kill",
    "wait",
    "write_stdin",
    "submit_stdin",
    "close_stdin",
]

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
    action: _BASH_PROCESS_ACTIONS = Field(
        description=(
            "list: all background jobs in this session (includes last_progress when available); "
            "output: tail stdout/stderr for pid; "
            "wait: block until pid exits or timeout_seconds (max 120); "
            "kill: stop pid (SIGTERM unless force=true); "
            "write_stdin: send raw bytes to pid stdin (no newline); "
            "submit_stdin: send data plus Enter (for y/n prompts); "
            "close_stdin: send EOF to close stdin."
        ),
    )
    pid: int | None = Field(
        default=None,
        description="Required for output, wait, kill, and stdin actions.",
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
    timeout_seconds: int = Field(
        default=_WAIT_DEFAULT_SECONDS,
        description=f"For wait: seconds to block (1-{_WAIT_MAX_SECONDS}). Returns still_running on timeout.",
        ge=1,
        le=_WAIT_MAX_SECONDS,
    )
    force: bool = Field(
        default=False,
        description="For kill: send SIGKILL when true, else SIGTERM first.",
    )
    filter: str | None = Field(
        default=None,
        description=(
            "For output: optional regex applied per line — only matching stdout/stderr lines are returned."
        ),
    )
    data: str = Field(
        default="",
        description=(
            "For write_stdin/submit_stdin: text to send to the process stdin "
            "(e.g. 'y' to confirm an installer prompt)."
        ),
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
    filter_pattern: str | None,
) -> dict[str, object]:
    registry = get_background_registry()
    info = registry.get(pid)
    if info is None or info.session_id != session_id:
        return {
            "content": f"No background process with pid={pid} in this session.",
            "metadata": {"pid": pid, "found": False, "action": "output"},
        }
    line_filter = None
    if filter_pattern:
        from myrm_agent_harness.agent.meta_tools.bash._bash_output_filter_core import (
            compile_output_filter,
        )

        try:
            line_filter = compile_output_filter(filter_pattern)
        except re.error as exc:
            return {
                "content": f"Invalid output filter regex: {exc}",
                "metadata": {
                    "pid": pid,
                    "found": True,
                    "action": "output",
                    "error": "invalid_filter",
                },
            }

    streams = registry.get_output(pid, max_lines=max_lines, since_cursor=since_cursor)
    stdout = streams["stdout"]
    stderr = streams["stderr"]
    if line_filter is not None:
        from myrm_agent_harness.agent.meta_tools.bash._bash_output_filter_core import (
            filter_output_lines,
        )

        stdout = filter_output_lines(
            list(stdout) if isinstance(stdout, list) else [], line_filter
        )
        stderr = filter_output_lines(
            list(stderr) if isinstance(stderr, list) else [], line_filter
        )

    poll_hint = streams.get("poll_hint")
    metadata: dict[str, object] = {
        "pid": pid,
        "session_id": session_id,
        "action": "output",
    }
    if filter_pattern:
        metadata["filter"] = filter_pattern
    if isinstance(poll_hint, dict):
        metadata["poll_hint"] = poll_hint
    return {
        "content": {
            "pid": pid,
            "status": info.status,
            "exit_code": info.exit_code,
            "error_category": info.error_category,
            "stdout": stdout,
            "stderr": stderr,
            "next_cursor": streams["next_cursor"],
            "dropped": streams["dropped"],
            "poll_hint": poll_hint,
        },
        "metadata": metadata,
    }


async def _handle_wait(
    session_id: str, pid: int, timeout_seconds: int
) -> dict[str, object]:
    registry = get_background_registry()
    info = registry.get(pid)
    if info is None or info.session_id != session_id:
        return {
            "content": f"No background process with pid={pid} in this session.",
            "metadata": {"pid": pid, "found": False, "action": "wait"},
        }
    result = await registry.wait_for_process(
        pid, timeout_seconds=float(timeout_seconds)
    )
    still_running = bool(result.get("still_running"))
    content: dict[str, object] = {
        "pid": pid,
        "still_running": still_running,
        "status": result.get("status"),
        "exit_code": result.get("exit_code"),
        "error_category": result.get("error_category"),
    }
    if still_running:
        content["message"] = (
            f"pid={pid} still running after {timeout_seconds}s; poll with action=output or wait again."
        )
    else:
        streams = registry.get_output(pid, max_lines=_OUTPUT_DEFAULT_LINES)
        content["stdout"] = streams.get("stdout", [])
        content["stderr"] = streams.get("stderr", [])
    return {
        "content": content,
        "metadata": {
            "pid": pid,
            "session_id": session_id,
            "action": "wait",
            "still_running": still_running,
        },
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
            f"Sent {'SIGKILL' if force else 'SIGTERM'} to pid={pid}"
            if ok
            else f"Failed to signal pid={pid}"
        ),
        "metadata": {
            "pid": pid,
            "force": force,
            "killed": ok,
            "session_id": session_id,
            "action": "kill",
        },
    }


async def _handle_stdin(
    session_id: str,
    pid: int,
    data: str,
    *,
    append_newline: bool,
    close: bool,
    action: str,
) -> dict[str, object]:
    registry = get_background_registry()
    info = registry.get(pid)
    if info is None or info.session_id != session_id:
        return {
            "content": f"No background process with pid={pid} in this session.",
            "metadata": {"pid": pid, "found": False, "action": action},
        }
    result = await registry.write_stdin(
        pid,
        data,
        append_newline=append_newline,
        close=close,
    )
    ok = bool(result.get("ok"))
    return {
        "content": result,
        "metadata": {
            "pid": pid,
            "session_id": session_id,
            "action": action,
            "ok": ok,
        },
    }


def create_bash_process_tool() -> BaseTool:
    """Return the unified background process management tool."""

    @tool(
        BASH_PROCESS_TOOL_NAME,
        description=(
            "Manage background bash processes started with bash_code_execute_tool(run_in_background=true). "
            "Actions: list (session jobs + last_progress), output (tail/ incremental poll via since_cursor), "
            "wait (block until exit or timeout_seconds, max 120), kill (SIGTERM or force SIGKILL), "
            "write_stdin (raw stdin), submit_stdin (stdin + Enter), close_stdin (EOF)."
        ),
        args_schema=_BashProcessInput,
    )
    async def _bash_process(
        action: _BASH_PROCESS_ACTIONS,
        pid: int | None = None,
        max_lines: int = _OUTPUT_DEFAULT_LINES,
        since_cursor: int | None = None,
        timeout_seconds: int = _WAIT_DEFAULT_SECONDS,
        force: bool = False,
        filter: str | None = None,
        data: str = "",
        *,
        config: RunnableConfig,
    ) -> dict[str, object]:
        session_id = _extract_session_id(config)
        if session_id is None:
            return _MISSING_SESSION_PAYLOAD

        if action == "list":
            return await _handle_list(session_id)

        pid_required = {
            "output",
            "kill",
            "wait",
            "write_stdin",
            "submit_stdin",
            "close_stdin",
        }
        if action in pid_required and pid is None:
            return {
                "content": f"action={action!r} requires pid.",
                "metadata": {"error": "missing_pid", "action": action},
            }

        if action == "output":
            assert pid is not None
            return await _handle_output(
                session_id, pid, max_lines, since_cursor, filter
            )
        if action == "wait":
            assert pid is not None
            return await _handle_wait(session_id, pid, timeout_seconds)
        if action == "kill":
            assert pid is not None
            return await _handle_kill(session_id, pid, force)
        if action == "write_stdin":
            assert pid is not None
            return await _handle_stdin(
                session_id,
                pid,
                data,
                append_newline=False,
                close=False,
                action=action,
            )
        if action == "submit_stdin":
            assert pid is not None
            return await _handle_stdin(
                session_id,
                pid,
                data,
                append_newline=True,
                close=False,
                action=action,
            )
        if action == "close_stdin":
            assert pid is not None
            return await _handle_stdin(
                session_id,
                pid,
                "",
                append_newline=False,
                close=True,
                action=action,
            )

        return {
            "content": (
                "Unknown action. Use list, output, wait, kill, write_stdin, "
                "submit_stdin, or close_stdin."
            ),
            "metadata": {"error": "invalid_action"},
        }

    return _bash_process


__all__ = [
    "BASH_PROCESS_TOOL_NAME",
    "create_bash_process_tool",
]
