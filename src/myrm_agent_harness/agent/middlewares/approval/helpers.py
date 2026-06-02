"""Approval middleware helper functions.

[INPUT]
- agent.security.approval_flow::AllowlistEntry (POS: Core component for "Always Allow" feature in Human-in-the-Loop approval system. Works with middlewares/approval/ subsystem which uses LangGraph interrupt() for approval flow. Allow-always decisions use database persistence (DBAllowlistStore): User clicks "Always Allow" → saved to user_tool_allowlist table On restart → middleware lazy-loads rules via allowlist.load_user() Rules survive backend restarts TTL refresh (default 5min) ensures multi-instance cache consistency when ttl_seconds > 0 ttl_seconds <= 0 disables time-based expiry and opportunistic TTL cleanup Automatic cleanup prevents memory leaks when TTL is enabled (expired locks removed opportunistically))

[OUTPUT]
- reset_denial_counter: Reset per-run denial counters. Call at the start of each ...
- record_denial: Increment denial counter and return guidance + threshold status.
- record_approval: Reset consecutive denial counter on successful operation.
- is_threshold_breached: Check if denial thresholds have been breached.
- add_to_allowlist_if_needed: Add permission to user's allowlist if requested.

[POS]
Approval middleware helper functions. Implements dual-threshold denial tracking
(consecutive + total) with proactive guidance on every denial and automatic
consecutive counter reset on any allowed operation.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum

from myrm_agent_harness.agent.security.approval_flow import AllowlistEntry, get_allowlist

logger = logging.getLogger(__name__)

_CONSECUTIVE_THRESHOLD = 3
_TOTAL_THRESHOLD = 20


class ThresholdBreach(StrEnum):
    """Which denial threshold was breached."""
    NONE = "none"
    CONSECUTIVE = "consecutive"
    TOTAL = "total"


@dataclass
class DenialState:
    """Session-scoped denial tracking state."""
    per_tool: dict[str, int] = field(default_factory=dict)
    consecutive: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class DenialResult:
    """Return value from record_denial."""
    hint: str
    breach: ThresholdBreach
    consecutive_count: int
    total_count: int


_denial_state_var: ContextVar[DenialState] = ContextVar("denial_state")


def _get_state() -> DenialState:
    try:
        return _denial_state_var.get()
    except LookupError:
        state = DenialState()
        _denial_state_var.set(state)
        return state


def reset_denial_counter() -> None:
    """Reset per-run denial counters. Call at the start of each Agent run."""
    _denial_state_var.set(DenialState())


def record_denial(tool_name: str) -> str:
    """Increment denial counters and return proactive guidance hint.

    Every denial gets a guidance message telling the agent to find a
    safer alternative.  When a threshold is breached, the message
    escalates to indicate that auto-mode will be suspended.

    Returns a hint string to append to the denial ToolMessage.
    """
    state = _get_state()
    state.per_tool[tool_name] = state.per_tool.get(tool_name, 0) + 1
    state.consecutive += 1
    state.total += 1

    breach = _check_breach(state)
    return _build_hint(state, breach)


def record_approval() -> None:
    """Reset consecutive denial counter on a successful allowed operation."""
    state = _get_state()
    if state.consecutive > 0:
        state.consecutive = 0


def is_threshold_breached() -> ThresholdBreach:
    """Check current denial state against thresholds without incrementing."""
    return _check_breach(_get_state())


def _check_breach(state: DenialState) -> ThresholdBreach:
    if state.total >= _TOTAL_THRESHOLD:
        return ThresholdBreach.TOTAL
    if state.consecutive >= _CONSECUTIVE_THRESHOLD:
        return ThresholdBreach.CONSECUTIVE
    return ThresholdBreach.NONE


def _build_hint(state: DenialState, breach: ThresholdBreach) -> str:
    base_guidance = (
        "\n\n[System: This action was denied. "
        "Find a safer alternative approach to achieve the user's goal. "
        "Do NOT attempt to circumvent or route around the security block.]"
    )

    if breach == ThresholdBreach.TOTAL:
        return (
            f"\n\n[System: {state.total} total denials in this session "
            f"(threshold: {_TOTAL_THRESHOLD}). Auto-mode is being suspended — "
            "all subsequent actions will require explicit human approval. "
            "Explain to the user what happened and ask for guidance.]"
        )

    if breach == ThresholdBreach.CONSECUTIVE:
        return (
            f"\n\n[System: {state.consecutive} consecutive denials "
            f"(threshold: {_CONSECUTIVE_THRESHOLD}). Auto-mode is being suspended — "
            "all subsequent actions will require explicit human approval. "
            "Stop and explain to the user what you were trying to do.]"
        )

    return base_guidance


async def add_to_allowlist_if_needed(
    allow_always: bool | dict, user_id: str, permission_type: str, tool_name: str, tool_args_hash: str | None = None
) -> None:
    """Add permission to user's allowlist if requested.

    Supports three matching levels:
    1. Permission-level: allow_always=True → matches all tools of this permission type
    2. Tool-level: allow_always={'tool': True} → matches this specific tool
    3. Exact match: allow_always={'tool': True, 'args': True} → matches tool + args (requires tool_args_hash)
    """
    if not allow_always or not user_id:
        return

    if isinstance(allow_always, bool):
        entry = AllowlistEntry(permission=permission_type, tool_name=None, tool_args_hash=None)
        log_msg = f"permission-level: ({permission_type}, *)"
    elif isinstance(allow_always, dict):
        match_args = allow_always.get("args", False)
        args_hash = tool_args_hash if match_args else None

        entry = AllowlistEntry(permission=permission_type, tool_name=tool_name, tool_args_hash=args_hash)
        if args_hash:
            log_msg = f"exact-match: ({permission_type}, {tool_name}, args_hash={args_hash})"
        else:
            log_msg = f"tool-level: ({permission_type}, {tool_name})"
    else:
        return

    await get_allowlist().add(user_id, entry)
    logger.info("[HITL] Added always-allow: %s", log_msg)
