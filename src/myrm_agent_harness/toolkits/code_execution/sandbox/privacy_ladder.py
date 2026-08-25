"""Sandbox privacy fail-closed ladder and event-driven persistence validation.

Provides defense-in-depth for cloud sandboxes and local persistent workspaces
across three distinct fail-closed privacy tiers:
- Tier 1 (File-Level): Sensitive credential/secret file blocking (.env, id_rsa, tokens, keys)
- Tier 2 (Session-Level): Session security mode enforcement (read-only/explore session blocking)
- Tier 3 (Workspace-Level): Boundary containment against physical directory traversal/symlink escape

[INPUT]
- myrm_agent_harness.core.security.path_security (POS: is_sensitive_file, is_dangerous_path, is_blocked_device_path)
- myrm_agent_harness.toolkits.code_execution.sandbox.mount_security_gate (POS: is_within_boundary, realpath resolution)

[OUTPUT]
- PrivacyTier (Enum: TIER_1_FILE, TIER_2_SESSION, TIER_3_WORKSPACE)
- PrivacyLadderViolationType (Enum: SENSITIVE_CREDENTIAL, READONLY_SESSION_MUTATION, WORKSPACE_ESCAPE, DANGEROUS_SYSTEM_PATH, BLOCKED_DEVICE)
- PrivacyLadderScope (immutable dataclass defining session permissions)
- PrivacyLadderResult (immutable dataclass)
- validate_privacy_ladder(target_path, session_scope, workspace_root) -> PrivacyLadderResult
- validate_and_sanitize_persistence_paths(paths, session_scope, workspace_root) -> tuple[str, ...]

[POS]
Toolkit Sandbox Security Domain component ensuring all persistence writes and snapshots strictly conform to privacy rules.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.core.security.path_security import (
    is_blocked_device_path,
    is_dangerous_path,
    is_sensitive_file,
)

logger = logging.getLogger(__name__)


class PrivacyTier(StrEnum):
    """Privacy validation tier."""

    TIER_1_FILE = "tier_1_file"
    TIER_2_SESSION = "tier_2_session"
    TIER_3_WORKSPACE = "tier_3_workspace"


class PrivacyLadderViolationType(StrEnum):
    """Specific classification of a privacy ladder violation."""

    SENSITIVE_CREDENTIAL = "sensitive_credential"
    READONLY_SESSION_MUTATION = "readonly_session_mutation"
    WORKSPACE_ESCAPE = "workspace_escape"
    DANGEROUS_SYSTEM_PATH = "dangerous_system_path"
    BLOCKED_DEVICE = "blocked_device"
    EMPTY_PATH = "empty_path"
    NULL_BYTE = "null_byte"


@dataclass(frozen=True, slots=True)
class PrivacyLadderScope:
    """Session scope configuration for privacy ladder validation."""

    is_read_only: bool = False
    allow_workspace_persistence: bool = True
    session_id: str = ""
    user_id: str = ""


@dataclass(frozen=True, slots=True)
class PrivacyLadderResult:
    """Immutable result of privacy ladder validation."""

    is_allowed: bool
    tier: PrivacyTier | None = None
    violation: PrivacyLadderViolationType | None = None
    reason: str = ""
    target_path: str = ""


# Dedicated sensitive file extension/name extra blacklist for sandbox persistence
_EXTRA_PERSISTENCE_SECRET_PATTERNS: tuple[str, ...] = (
    ".env*",
    "*.key",
    "*.pem",
    "id_rsa*",
    "id_ed25519*",
    "*.pfx",
    "*.p12",
    "*.kdbx",
    "credentials.json",
    "secrets.json",
    "token_*.json",
    "auth_*.json",
)


def _is_persistence_secret(path_str: str) -> bool:
    """Check if file matches extra persistence secret patterns."""
    from fnmatch import fnmatch

    name = Path(path_str).name
    lower_name = name.lower()
    for pattern in _EXTRA_PERSISTENCE_SECRET_PATTERNS:
        if fnmatch(lower_name, pattern.lower()):
            return True
    return False


def validate_privacy_ladder(
    target_path: str,
    session_scope: PrivacyLadderScope,
    workspace_root: str,
) -> PrivacyLadderResult:
    """Validate a path against the 3-tier privacy fail-closed ladder.

    Args:
        target_path: The file/dir path intended for persistence write or snapshot.
        session_scope: The session context holding read-only flags and permissions.
        workspace_root: The authorized physical workspace boundary.

    Returns:
        A PrivacyLadderResult indicating whether the write is permitted or blocked.
    """
    if not target_path or not isinstance(target_path, str) or not target_path.strip():
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_1_FILE,
            violation=PrivacyLadderViolationType.EMPTY_PATH,
            reason="Target path is empty or invalid",
            target_path=target_path,
        )

    cleaned = target_path.strip()

    # Null byte defense
    if "\x00" in cleaned:
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_1_FILE,
            violation=PrivacyLadderViolationType.NULL_BYTE,
            reason="Target path contains null byte injection",
            target_path=cleaned,
        )

    # -----------------------------------------------------------------------
    # Tier 2: Session-Level Validation (Fast Gate)
    # -----------------------------------------------------------------------
    if session_scope.is_read_only or not session_scope.allow_workspace_persistence:
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_2_SESSION,
            violation=PrivacyLadderViolationType.READONLY_SESSION_MUTATION,
            reason="Session is configured as read-only or workspace persistence is disabled",
            target_path=cleaned,
        )

    # -----------------------------------------------------------------------
    # Tier 1: File-Level Validation (Sensitive credentials, system roots, devices)
    # -----------------------------------------------------------------------
    if is_blocked_device_path(cleaned):
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_1_FILE,
            violation=PrivacyLadderViolationType.BLOCKED_DEVICE,
            reason=f"Target path '{cleaned}' references a blocked device",
            target_path=cleaned,
        )

    if is_dangerous_path(cleaned):
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_1_FILE,
            violation=PrivacyLadderViolationType.DANGEROUS_SYSTEM_PATH,
            reason=f"Target path '{cleaned}' is a protected system directory",
            target_path=cleaned,
        )

    if is_sensitive_file(cleaned) or _is_persistence_secret(cleaned):
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_1_FILE,
            violation=PrivacyLadderViolationType.SENSITIVE_CREDENTIAL,
            reason=f"Target path '{cleaned}' matches sensitive credential/secret blacklist",
            target_path=cleaned,
        )

    # -----------------------------------------------------------------------
    # Tier 3: Workspace-Level Validation (Boundary containment & Symlink escape)
    # -----------------------------------------------------------------------
    if not workspace_root or not workspace_root.strip():
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_3_WORKSPACE,
            violation=PrivacyLadderViolationType.WORKSPACE_ESCAPE,
            reason="Workspace boundary is not configured",
            target_path=cleaned,
        )

    ws_clean = workspace_root.strip()
    try:
        ws_real = os.path.realpath(os.path.abspath(ws_clean))
        target_abs = os.path.abspath(
            cleaned if os.path.isabs(cleaned) else os.path.join(ws_real, cleaned)
        )
        target_real = os.path.realpath(target_abs)
    except Exception as exc:
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_3_WORKSPACE,
            violation=PrivacyLadderViolationType.WORKSPACE_ESCAPE,
            reason=f"Failed to resolve realpath for '{cleaned}': {exc}",
            target_path=cleaned,
        )

    is_case_insensitive = platform.system() in ("Darwin", "Windows")
    cmp_target = target_real.lower() if is_case_insensitive else target_real
    cmp_ws = ws_real.lower() if is_case_insensitive else ws_real

    if cmp_target != cmp_ws and not cmp_target.startswith(cmp_ws + os.sep.lower() if is_case_insensitive else cmp_ws + os.sep):
        return PrivacyLadderResult(
            is_allowed=False,
            tier=PrivacyTier.TIER_3_WORKSPACE,
            violation=PrivacyLadderViolationType.WORKSPACE_ESCAPE,
            reason=f"Target path '{cleaned}' escapes workspace root '{workspace_root}'",
            target_path=cleaned,
        )

    return PrivacyLadderResult(
        is_allowed=True,
        tier=None,
        violation=None,
        reason="",
        target_path=cleaned,
    )


def validate_and_sanitize_persistence_paths(
    paths: list[str] | tuple[str, ...],
    session_scope: PrivacyLadderScope,
    workspace_root: str,
) -> tuple[str, ...]:
    """Filter a list of candidate persistence paths, returning only allowed paths.

    Args:
        paths: List or tuple of candidate paths.
        session_scope: Session privacy scope.
        workspace_root: Authorized workspace boundary.

    Returns:
        Tuple of sanitized paths that passed all 3 privacy tiers.
    """
    if not paths:
        return ()

    sanitized: list[str] = []
    for path in paths:
        result = validate_privacy_ladder(path, session_scope, workspace_root)
        if result.is_allowed:
            sanitized.append(path)
        else:
            logger.warning(
                "[PrivacyLadderGate] Blocked persistence for '%s' (Tier: %s, Violation: %s): %s",
                path,
                result.tier,
                result.violation,
                result.reason,
            )

    return tuple(sanitized)
