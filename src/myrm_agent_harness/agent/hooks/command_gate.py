"""Command hook safety gate, payload binding and approval injection point.

Shell-command hooks spawn a subprocess that the code_execution safety
family does not cover. This gate reuses the same static command analyzer
(``analyze_command``) so command hooks are judged by the same rules as
agent bash commands, with one deliberate difference: shell *syntax*
(``;``, ``$()``, ``${}``, backticks, redirects) is ordinary in a hook a
person wrote, so only the categories describing what a command *does*
apply:

- BLOCK-level threats (dangerous commands, obfuscation, control
  characters) are refused unconditionally.
- ESCALATE-level threats are refused in ``strict`` mode — used for hooks
  from third-party provenance (skill/plugin/user config), because hooks
  fire silently and unreviewed commands only get the narrowest path.
  Built-in framework hooks keep the wider path.
- The gate judges the authored command template, never the event payload,
  so a hook gets the same verdict for every event.
- Event data reaches the command only as a ``$HOOK_PAYLOAD`` reference
  (``bind_payload_reference``), never as pasted text, so it cannot be
  parsed as code. The variable is clipped to what one environment string
  can carry (``payload_env_value``); the complete payload is piped to stdin.
- A product-layer approver (server approval card) can be injected via
  ``set_command_hook_approver`` to override a refusal at runtime.

[INPUT]
- agent.hooks.types (POS: Hook 类型定义，含 priority/source 治理字段)
- toolkits.code_execution.security.shell_command_analyzer (POS: 命令静态安全分析器)
- utils.logger_utils (POS: 日志工具)

[OUTPUT]
- HookCommandApprover, get/set_command_hook_approver: approval injection point
- gate_hook_command: static gate check on the command template (BLOCK always; ESCALATE in strict mode)
- bind_payload_reference, PAYLOAD_ENV_VAR: rewrite $ARGUMENTS into an inert $HOOK_PAYLOAD reference
- payload_env_value, MAX_PAYLOAD_ENV_CHARS: the $HOOK_PAYLOAD value, clipped to fit one environment string
- approve_hook_command: ask the injected approver to override a refusal
- merged_governance_metadata: attach source/priority provenance to results

[POS]
Command hook safety gate. Runs command-type hooks through the code_execution
static analyzer before spawn, keeps event data out of the command text, with a
product-layer approval injection point; absent approver means the gate verdict
stands (fail-closed for third-party hooks).
"""

from __future__ import annotations

import asyncio
import json
import re
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

# Shell-syntax vectors (``$()``, backticks, ``${}``, ``;``, process substitution)
# police LLM-generated one-liners. In a hook a person wrote or reviewed they are
# ordinary shell, and refusing them rejects most real hooks. Control-character
# smuggling is categorised separately by the analyzer and is never waived.
_WAIVED_BLOCK_CATEGORIES = frozenset({"injection"})


def gate_hook_command(command: str, *, strict: bool) -> str | None:
    """Return the refusal reason when a hook command template trips the static gate.

    Reuses the code_execution command analyzer (same rules as agent bash),
    minus the shell-syntax style policy. BLOCK-level threats are refused
    unconditionally; in ``strict`` mode — used for third-party hooks
    (skill/plugin/user config) — ESCALATE-level threats are refused too:
    hooks fire silently, so unreviewed commands only get the narrowest path.
    Returns None when the command is allowed.
    """
    from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
        ThreatLevel,
        analyze_command,
    )

    for threat in analyze_command(command):
        if threat.level == ThreatLevel.BLOCK:
            if threat.category in _WAIVED_BLOCK_CATEGORIES:
                continue
            return f"blocked pattern: {threat.detail}"
        if strict and threat.level == ThreatLevel.ESCALATE:
            return f"unreviewed hook escalation: {threat.detail}"
    return None


def is_strict_source(hook: HookDefinition) -> bool:
    """Third-party provenance gets the strict (narrower) gate path."""
    return hook.source is not HookSource.BUILTIN


# ---------------------------------------------------------------------------
# Payload binding (event data never becomes command text)
# ---------------------------------------------------------------------------

PAYLOAD_ENV_VAR = "HOOK_PAYLOAD"
"""Environment variable carrying the JSON event payload to the hook command."""

_PAYLOAD_PLACEHOLDER = re.compile(r"\$ARGUMENTS(?![A-Za-z0-9_])")
_UNQUOTED_REFERENCE = f'"${PAYLOAD_ENV_VAR}"'
_QUOTED_REFERENCE = f"${PAYLOAD_ENV_VAR}"
_QUOTES = "'\""


def bind_payload_reference(command: str) -> str:
    """Rewrite each ``$ARGUMENTS`` into a reference to the payload env var.

    The payload carries event data (tool output, user text) an attacker can
    shape. Pasting it into the command text — however shell-escaped — lets
    that data be parsed as code in some quoting contexts (``"$ARGUMENTS"``
    closes the escaping quotes). A variable reference is expanded by the
    shell without being re-parsed, so the data stays inert in every context.

    The reference follows the quoting context so the hook always receives
    the JSON as one word:

    - unquoted:       ``$ARGUMENTS``      -> ``"$HOOK_PAYLOAD"``
    - double-quoted:  ``"a=$ARGUMENTS"``  -> ``"a=$HOOK_PAYLOAD"``
    - single-quoted or backslash-escaped placeholders stay literal: the shell
      never expands them, and an inner ``sh -c '...'`` must not re-parse data.
    """
    out: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        char = command[i]
        if char == "\\" and quote != "'":
            out.append(command[i : i + 2])
            i += 2
            continue
        if char == "$" and quote != "'":
            placeholder = _PAYLOAD_PLACEHOLDER.match(command, i)
            if placeholder:
                out.append(_QUOTED_REFERENCE if quote else _UNQUOTED_REFERENCE)
                i = placeholder.end()
                continue
        if char in _QUOTES and quote in ("", char):
            quote = "" if quote else char
        out.append(char)
        i += 1
    return "".join(out)


MAX_PAYLOAD_ENV_CHARS = 96 * 1024
"""Largest ``$HOOK_PAYLOAD`` value. A single environment string tops out at 128 KiB on Linux
(``MAX_ARG_STRLEN``) and all arguments plus environment at about 1 MiB on macOS; a larger value
makes the spawn fail with E2BIG and the hook would never run."""

_CLIP_STEPS = (16_384, 4_096, 1_024, 256, 64)
"""String lengths tried in turn when clipping an oversized payload, longest first."""


def _clip_strings(value: object, limit: int) -> object:
    """Copy of a decoded JSON value with every string cut to ``limit`` characters."""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return {key: _clip_strings(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip_strings(item, limit) for item in value]
    return value


def payload_env_value(full_json: str) -> str:
    """The ``$HOOK_PAYLOAD`` value for an event payload serialized as ASCII JSON.

    A payload that fits in one environment string is passed as is. A larger one (a tool call
    carrying a whole file, a long tool output) is clipped by shortening its long string values,
    keeping its structure and adding ``"payload_truncated": true``; the hook still has the
    complete payload on stdin. A payload that stays too large after clipping (thousands of
    short values) is reduced to its top-level key names.
    """
    if len(full_json) <= MAX_PAYLOAD_ENV_CHARS:
        return full_json
    decoded: dict[str, object] = json.loads(full_json)
    marked = {**decoded, "payload_truncated": True}
    for limit in _CLIP_STEPS:
        clipped = json.dumps(_clip_strings(marked, limit), ensure_ascii=True)
        if len(clipped) <= MAX_PAYLOAD_ENV_CHARS:
            return clipped
    return json.dumps({"payload_truncated": True, "keys": sorted(decoded)}, ensure_ascii=True)


# ---------------------------------------------------------------------------
# Approval + provenance
# ---------------------------------------------------------------------------


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
