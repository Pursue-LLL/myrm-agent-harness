"""Dual-track fault-site overlay synthesis engine.

[INPUT]
- re, uuid (POS: Python standard library)
- .schema::(OverlayScope, OverlayTargetType, SessionOverlay, OverlayStatus)

[OUTPUT]
- synthesize_fault_site_overlay(): Dual-track synthesis from tool exceptions
- synthesize_loop_stall_overlay(): Synthesis from LoopGuard stall events

[POS]
Generates deterministic, zero-LLM session overlays for tool execution errors
and agent execution deadlocks based on Continual Harness principles.
"""

from __future__ import annotations

import re
import uuid

from myrm_agent_harness.agent.session_overlay.schema import (
    OverlayScope,
    OverlayStatus,
    OverlayTargetType,
    SessionOverlay,
)

_RE_EXTRA_FIELD = re.compile(
    r"(?:extra field|unexpected keyword argument|unrecognized argument|got an unexpected keyword argument)\s+['\"]?([a-zA-Z0-9_\-]+)['\"]?",
    re.IGNORECASE,
)
_RE_PYDANTIC_LOC = re.compile(r"loc':\s*\('([a-zA-Z0-9_\-]+)',?\)", re.IGNORECASE)
_RE_UNKNOWN_PARAM = re.compile(r"Unknown parameter:\s+([a-zA-Z0-9_\-]+)", re.IGNORECASE)


def _extract_forbidden_field(error_msg: str) -> str | None:
    """Extract illegal or extra parameter name from error trace."""
    match = _RE_EXTRA_FIELD.search(error_msg)
    if match:
        return match.group(1)
    loc_match = _RE_PYDANTIC_LOC.search(error_msg)
    if loc_match:
        return loc_match.group(1)
    unknown_match = _RE_UNKNOWN_PARAM.search(error_msg)
    if unknown_match:
        return unknown_match.group(1)
    return None


FATAL_SYSTEM_ERROR_NAMES: tuple[type[BaseException], ...] = (
    MemoryError,
    PermissionError,
    KeyboardInterrupt,
    SystemExit,
)

_FATAL_ERROR_PATTERNS: tuple[str, ...] = (
    "out of memory",
    "cuda out of memory",
    "permission denied",
    "disk full",
    "enospc",
    "unauthorized",
    "status code 401",
    "status code 403",
)


def synthesize_fault_site_overlay(
    tool_name: str,
    error: Exception | str = "",
    tool_args: dict[str, object] | None = None,
    current_turn: int = 1,
    scope: OverlayScope = OverlayScope.SESSION,
    *,
    error_category: str | None = None,
    error_message: str | None = None,
    session_id: str = "",
) -> SessionOverlay | None:
    """Synthesize a zero-overhead session overlay from a tool execution failure.

    Uses L0 deterministic regex rules and L1 ValidationError AST parsing to produce
    a localized argument-stripping adapter or negative constraint.
    """
    if isinstance(error, FATAL_SYSTEM_ERROR_NAMES):
        return None

    error_msg = error_message if error_message is not None else str(error)
    error_msg_lower = error_msg.lower()
    if any(pat in error_msg_lower for pat in _FATAL_ERROR_PATTERNS):
        return None

    args_dict = tool_args or {}
    overlay_uid = f"ovl-{uuid.uuid4().hex[:8]}"
    sig = f"{tool_name}:{error_category or (type(error).__name__ if isinstance(error, Exception) else 'Error')}"

    # L0/L1: Unknown / extra argument error -> TEMP_SKILL_VARIANT with strip_params
    bad_field = _extract_forbidden_field(error_msg)
    if bad_field and (not args_dict or bad_field in args_dict):
        advisory = f"Tool '{tool_name}' rejected extra parameter '{bad_field}'. In subsequent calls, omit '{bad_field}'."
        return SessionOverlay(
            overlay_id=overlay_uid,
            scope=scope,
            target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
            target_name=tool_name,
            patch_payload={
                "action": "strip_and_alias",
                "strip_params": [bad_field],
                "reason": f"Tool '{tool_name}' rejected argument '{bad_field}'",
                "advisory_instruction": advisory,
            },
            ttl_turns=3,
            max_attempts=1,
            failure_signature=f"{sig}:extra_arg_{bad_field}",
            created_at_turn=current_turn,
            status=OverlayStatus.ACTIVE,
            snapshot_id=f"snap-{overlay_uid}",
        )

    # L0: Timeout / Deadline Exceeded -> PROMPT_PATCH or PROCEDURAL_MEMORY
    if "timeout" in error_msg.lower() or "deadline" in error_msg.lower():
        timeout_hint = (
            f"Prior call to '{tool_name}' timed out. In the next 3 turns, "
            "reduce query complexity, narrow search scopes, or split the task into smaller batches."
        )
        return SessionOverlay(
            overlay_id=overlay_uid,
            scope=scope,
            target_type=OverlayTargetType.PROCEDURAL_MEMORY,
            target_name=tool_name,
            patch_payload={
                "action": "negative_constraint",
                "negative_constraint": timeout_hint,
                "advisory_instruction": timeout_hint,
            },
            ttl_turns=3,
            max_attempts=1,
            failure_signature=f"{sig}:timeout",
            created_at_turn=current_turn,
            status=OverlayStatus.ACTIVE,
            snapshot_id=f"snap-{overlay_uid}",
        )

    # L0: File / Path Not Found -> Procedural Memory hint
    if "not found" in error_msg.lower() or "no such file" in error_msg.lower():
        not_found_hint = (
            f"Target resource in '{tool_name}' was not found. "
            "Verify file existence or inspect current directory before retrying."
        )
        return SessionOverlay(
            overlay_id=overlay_uid,
            scope=scope,
            target_type=OverlayTargetType.PROCEDURAL_MEMORY,
            target_name=tool_name,
            patch_payload={
                "action": "negative_constraint",
                "negative_constraint": not_found_hint,
                "advisory_instruction": not_found_hint,
            },
            ttl_turns=3,
            max_attempts=1,
            failure_signature=f"{sig}:not_found",
            created_at_turn=current_turn,
            status=OverlayStatus.ACTIVE,
            snapshot_id=f"snap-{overlay_uid}",
        )

    # L0: Rate limit / 429 Too Many Requests -> PROCEDURAL_MEMORY backoff hint
    lower_err = error_msg.lower()
    if "429" in lower_err or "rate limit" in lower_err or "ratelimit" in lower_err or "quota" in lower_err:
        rate_limit_hint = (
            f"Prior call to '{tool_name}' triggered rate limit (429/quota). In the next 3 turns, "
            "apply backoff delay and reduce batch sizes or payload volume."
        )
        return SessionOverlay(
            overlay_id=overlay_uid,
            scope=scope,
            target_type=OverlayTargetType.PROCEDURAL_MEMORY,
            target_name=tool_name,
            patch_payload={
                "action": "negative_constraint",
                "negative_constraint": rate_limit_hint,
                "advisory_instruction": rate_limit_hint,
            },
            ttl_turns=3,
            max_attempts=1,
            failure_signature=f"{sig}:rate_limit",
            created_at_turn=current_turn,
            status=OverlayStatus.ACTIVE,
            snapshot_id=f"snap-{overlay_uid}",
        )

    return None


def synthesize_loop_stall_overlay(
    loop_kind: str,
    tool_name: str,
    current_turn: int = 1,
    scope: OverlayScope = OverlayScope.SESSION,
) -> SessionOverlay:
    """Synthesize a procedural memory constraint from a LoopGuard stall/warning."""
    overlay_uid = f"ovl-stall-{uuid.uuid4().hex[:8]}"
    constraint = (
        f"LoopGuard warning [{loop_kind}] detected on '{tool_name}'. "
        f"For the next 3 turns, do not repeat identical invocations on '{tool_name}'. "
        "Switch to an alternative tool or read current progress."
    )
    return SessionOverlay(
        overlay_id=overlay_uid,
        scope=scope,
        target_type=OverlayTargetType.PROCEDURAL_MEMORY,
        target_name=tool_name,
        patch_payload={
            "action": "negative_constraint",
            "negative_constraint": constraint,
            "loop_kind": loop_kind,
        },
        ttl_turns=3,
        max_attempts=1,
        failure_signature=f"loopguard:{loop_kind}:{tool_name}",
        created_at_turn=current_turn,
        status=OverlayStatus.ACTIVE,
        snapshot_id=f"snap-{overlay_uid}",
    )
