"""Auto WAIT for whitelisted long-running background bash commands.

[INPUT]
- agent.security.guards.loop_guard_types::CallRecord (POS: tool call window entries)
- agent.middlewares.tool_interceptor_middleware::get_loop_guard (POS: session LoopGuard)

[OUTPUT]
- is_wait_eligible_command: Narrow whitelist for build/test/CI commands
- find_latest_background_spawn_in_window: Detect background spawn from LoopGuard window
- WAIT_ON_BACKGROUND_PID_KEY: Metadata key linking WAIT to a background pid

[POS]
Goal continuation helper — parks the goal loop when a whitelisted background bash
job starts, without injecting process lists into the semantic judge (Prompt Cache safe).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord

WAIT_ON_BACKGROUND_PID_KEY = "wait_on_background_pid"

_BASH_TOOL = "bash_code_execute_tool"

_WAIT_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnpm\s+(run\s+)?(build|test|ci)\b", re.IGNORECASE),
    re.compile(r"\b(yarn|pnpm|bun)\s+(run\s+)?(build|test)\b", re.IGNORECASE),
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+(build|test)\b", re.IGNORECASE),
    re.compile(r"\bmake\s+(build|test|check|all)\b", re.IGNORECASE),
    re.compile(r"\bdocker\s+compose\s+(up|build)\b", re.IGNORECASE),
    re.compile(r"\bmvn\s+(package|test|verify)\b", re.IGNORECASE),
    re.compile(r"\bgradle\s+(build|test)\b", re.IGNORECASE),
)

_PID_FROM_RESULT_RE = re.compile(r"pid:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class BackgroundSpawnInfo:
    """Background bash spawn detected from a tool call record."""

    command: str
    pid: int


def is_wait_eligible_command(command: str) -> bool:
    """Return True when the command matches the narrow build/test/CI whitelist."""
    cmd = command.strip()
    if not cmd:
        return False
    return any(pattern.search(cmd) for pattern in _WAIT_COMMAND_PATTERNS)


def parse_background_spawn_from_record(
    tool_name: str,
    args: dict[str, object],
    result_content: str,
) -> BackgroundSpawnInfo | None:
    """Parse a LoopGuard record for a whitelisted background bash spawn."""
    if tool_name != _BASH_TOOL:
        return None
    if not args.get("run_in_background"):
        return None
    command = str(args.get("command", "")).strip()
    if not is_wait_eligible_command(command):
        return None
    match = _PID_FROM_RESULT_RE.search(result_content)
    if not match:
        return None
    return BackgroundSpawnInfo(command=command, pid=int(match.group(1)))


def find_latest_background_spawn_in_window(
    records: list[CallRecord],
) -> BackgroundSpawnInfo | None:
    """Return the most recent whitelisted background spawn in the LoopGuard window."""
    for record in reversed(records):
        info = parse_background_spawn_from_record(
            record.tool_name,
            record.args,
            record.result_content,
        )
        if info is not None:
            return info
    return None


__all__ = [
    "WAIT_ON_BACKGROUND_PID_KEY",
    "BackgroundSpawnInfo",
    "find_latest_background_spawn_in_window",
    "is_wait_eligible_command",
    "parse_background_spawn_from_record",
]
