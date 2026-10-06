"""Command hook safety gate and approval injection point.

Shell-command hooks spawn a subprocess that the code_execution safety
family does not cover. This gate reuses the same static command analyzer
(``analyze_command`` / ``is_destructive_command``) so command hooks are
judged by the same rules as agent bash commands:

- BLOCK-level threats are refused unconditionally.
- ESCALATE-level threats are refused in ``strict`` mode — used for hooks
  from third-party provenance (skill/plugin/user config), because hooks
  fire silently and unreviewed commands only get the narrowest path.
  Built-in framework hooks keep the wider path.
- A product-layer approver (server approval card) can be injected via
  ``set_command_hook_approver`` to override a refusal at runtime.

[INPUT]
- agent.hooks.types (POS: Hook 类型定义，含 priority/source 治理字段)
- toolkits.code_execution.security.shell_command_analyzer (POS: 命令静态安全分析器)
- utils.logger_utils (POS: 日志工具)

[OUTPUT]
- HookCommandApprover, get/set_command_hook_approver: approval injection point
- gate_hook_command: static gate check (BLOCK always; ESCALATE in strict mode)
- approve_hook_command: ask the injected approver to override a refusal
- merged_governance_metadata: attach source/priority provenance to results

[POS]
Command hook safety gate. Runs command-type hooks through the code_execution
static analyzer before spawn, with a product-layer approval injection point;
absent approver means the gate verdict stands (fail-closed for third-party
hooks).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from myrm_agent_harness.agent.hooks.types import CommandHookDefinition, HookDefinition, HookSource
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


# ---------------------------------------------------------------------------
# Approval injection point (product layer wires an approval card here)
# ---------------------------------------------------------------------------

HookCommandApprover = Callable[[CommandHookDefinition, str, str], Awaitable[bool]]
"""Async approval callback ``(hook, event, command) -> allow``.

Injected by the product layer (server) to surface an approval card for
command hooks refused by the safety gate. Absent by default: standalone
harness keeps the gate verdict (fail-closed for third-party hooks)."""

_command_approver_var: ContextVar[HookCommandApprover | None] = ContextVar("hook_command_approver", default=None)


def get_command_hook_approver() -> HookCommandApprover | None:
    """Get the session-scoped command hook approver, or None."""
    return _command_approver_var.get()


def set_command_hook_approver(approver: HookCommandApprover | None) -> None:
    """Set (or clear) the session-scoped command hook approver."""
    _command_approver_var.set(approver)


# ---------------------------------------------------------------------------
# Static gate
# ---------------------------------------------------------------------------


def gate_hook_command(command: str, *, strict: bool) -> str | None:
    """Return the refusal reason when a command trips the static safety gate.

    Reuses the code_execution command analyzer (same rules as agent bash).
    BLOCK-level threats are refused unconditionally; in ``strict`` mode —
    used for third-party hooks (skill/plugin/user config) — ESCALATE-level
    threats are refused too: hooks fire silently, so unreviewed commands
    only get the narrowest path. Returns None when the command is allowed.
    """
    from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
        ThreatLevel,
        analyze_command,
        is_destructive_command,
    )

    if is_destructive_command(command):
        return "destructive command"
    for threat in analyze_command(command):
        if threat.level == ThreatLevel.BLOCK:
            return f"blocked pattern: {threat.detail}"
        if strict and threat.level == ThreatLevel.ESCALATE:
            return f"unreviewed hook escalation: {threat.detail}"
    return None


def is_strict_source(hook: HookDefinition) -> bool:
    """Third-party provenance gets the strict (narrower) gate path."""
    return hook.source is not HookSource.BUILTIN


async def approve_hook_command(hook: CommandHookDefinition, event: str, command: str) -> bool:
    """Ask the injected approver (server approval card) to override a refusal.

    Always returns False when no approver is installed (standalone mode) —
    the gate verdict then stands.
    """
    approver = get_command_hook_approver()
    if approver is None:
        return False
    try:
        return bool(await asyncio.wait_for(approver(hook, event, command), timeout=hook.timeout_seconds))
    except TimeoutError:
        logger.warning("hooks: command approver timed out after %ss, treating as refused", hook.timeout_seconds)
        return False
    except Exception as exc:
        logger.warning("hooks: command approver raised, treating as refused: %s", exc)
        return False


def merged_governance_metadata(metadata: dict[str, object], hook: HookDefinition) -> dict[str, object]:
    """Attach governance provenance (source/priority) to hook result metadata."""
    merged = dict(metadata)
    merged["source"] = hook.source.value
    merged["priority"] = hook.priority
    return merged
