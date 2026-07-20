"""Auto-yield foreground whitelist commands into background after a short wait window.

[INPUT]
- agent.goals.wait_background_bash::is_wait_eligible_command (POS: build/test whitelist SSOT)
- ._background_registry::get_background_registry (POS: poll partial output)

[OUTPUT]
- DEFAULT_YIELD_AFTER_SECONDS: Profile-aligned default when arg omitted
- build_auto_yield_return: Compose tool payload after yield window

[POS]
Bash-tool helper — keeps bash_code_execute_tool aggregate root thin.
"""

from __future__ import annotations

import asyncio
import time

from myrm_agent_harness.agent.goals.wait_background_bash import is_wait_eligible_command
from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    BackgroundProcessRegistry,
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash._background_types import BackgroundProcessInfo

DEFAULT_YIELD_AFTER_SECONDS = 10
_POLL_INTERVAL_SECONDS = 0.25


def resolve_yield_seconds(yield_after_seconds: int | None) -> int | None:
    """Return effective yield window for whitelist commands, or None when disabled."""
    if yield_after_seconds == 0:
        return None
    if yield_after_seconds is not None:
        return max(1, yield_after_seconds)
    return DEFAULT_YIELD_AFTER_SECONDS


def should_auto_yield(*, command: str, run_in_background: bool, yield_after_seconds: int | None) -> bool:
    """True when a whitelist command should use the auto-yield background path."""
    if run_in_background:
        return False
    if not is_wait_eligible_command(command):
        return False
    return resolve_yield_seconds(yield_after_seconds) is not None


async def wait_for_yield_window(
    registry: BackgroundProcessRegistry,
    pid: int,
    *,
    yield_seconds: int,
) -> BackgroundProcessInfo | None:
    """Block until yield deadline or the background job exits."""
    deadline = time.monotonic() + float(yield_seconds)
    info: BackgroundProcessInfo | None = None
    while time.monotonic() < deadline:
        info = registry.get(pid)
        if info is None:
            return None
        if info.status != "running":
            return info
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    return registry.get(pid)


def build_auto_yield_return(
    *,
    info: BackgroundProcessInfo,
    yield_seconds: int,
    registry: BackgroundProcessRegistry | None = None,
) -> dict[str, object]:
    """Return tool payload after the yield window (completed early or still running)."""
    reg = registry or get_background_registry()
    streams = reg.get_output(info.pid, max_lines=50)
    stdout_lines = streams.get("stdout", [])
    stderr_lines = streams.get("stderr", [])
    stdout_text = "\n".join(str(line) for line in stdout_lines) if stdout_lines else ""
    stderr_text = "\n".join(str(line) for line in stderr_lines) if stderr_lines else ""

    if info.status != "running":
        parts = [f"Command finished during auto-yield window (pid={info.pid})."]
        if stdout_text:
            parts.append(stdout_text)
        if stderr_text:
            parts.append(f"[stderr]\n{stderr_text}")
        if info.exit_code is not None:
            parts.append(f"[exit_code: {info.exit_code}]")
        return {
            "content": "\n".join(parts),
            "metadata": {
                "auto_yielded": True,
                "completed_in_yield_window": True,
                "pid": info.pid,
                "exit_code": info.exit_code,
            },
        }

    hint = (
        f"Command still running after {yield_seconds}s — detached as background job.\n"
        f"  pid: {info.pid}\n"
        f"  command: {info.command}\n\n"
        "Use bash_process_tool(action='wait' or 'output', pid=...) to continue."
    )
    if stdout_text or stderr_text:
        hint += "\n\nPartial output:\n"
        if stdout_text:
            hint += stdout_text
        if stderr_text:
            hint += f"\n[stderr]\n{stderr_text}"

    poll_hint = streams.get("poll_hint")
    metadata: dict[str, object] = {
        "auto_yielded": True,
        "background": True,
        "pid": info.pid,
        "status": info.status,
    }
    if isinstance(poll_hint, dict):
        metadata["poll_hint"] = poll_hint

    return {"content": hint, "metadata": metadata}


__all__ = [
    "DEFAULT_YIELD_AFTER_SECONDS",
    "build_auto_yield_return",
    "resolve_yield_seconds",
    "should_auto_yield",
    "wait_for_yield_window",
]
