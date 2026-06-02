"""Built-in security checks — Layer 2 & 2.5 of the onion security architecture.

Path policy evaluation, URL scheme validation, and shell threat analysis.
All checks are pure functions — no side effects, no I/O, trivially testable.

[INPUT]

[OUTPUT]
- check_path_policy(): evaluate file path against PathPolicy (Layer 2.5)
- check_navigate_scheme(): validate browser_navigate URL scheme (Layer 2)
- check_shell_threats(): analyze shell commands for injection vectors (Layer 2)

[POS]
All check functions return ``(action_or_None, reason)`` tuples. ``None`` action
means the check does not apply (pass-through). Called by ``engine.evaluate_tool_call``.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from myrm_agent_harness.agent.security.types import PathPolicy, PermissionAction

# ---------------------------------------------------------------------------
# Path Policy — forbidden/allowed path zones for file operations (Layer 2.5)
# ---------------------------------------------------------------------------


def _normalize_path(raw: str) -> str:
    """Expand ~ and $HOME, resolve to absolute path for comparison."""
    return os.path.realpath(os.path.expanduser(os.path.expandvars(raw)))


def _is_subpath(child: str, parent: str) -> bool:
    """Check if child path is equal to or under parent directory."""
    return child == parent or child.startswith(parent + os.sep)


def check_path_policy(raw_path: str, policy: PathPolicy, workspace_root: str | None) -> tuple[PermissionAction, str]:
    """Evaluate a file path against the PathPolicy.

    Returns (DENY, reason) if blocked by forbidden paths, (ALLOW, "") if in allowed roots or workspace.
    Returns (ASK, reason) if outside allowed zones, requiring user approval.
    Relative paths are resolved against workspace_root when available.
    """
    if workspace_root and not os.path.isabs(os.path.expanduser(raw_path)):
        normalized = _normalize_path(os.path.join(workspace_root, raw_path))
    else:
        normalized = _normalize_path(raw_path)

    for fp in policy.forbidden_paths:
        if _is_subpath(normalized, _normalize_path(fp)):
            return PermissionAction.DENY, f"Path in forbidden zone: {raw_path}"

    for ar in policy.allowed_roots:
        if _is_subpath(normalized, _normalize_path(ar)):
            return PermissionAction.ALLOW, ""

    if workspace_root and _is_subpath(normalized, _normalize_path(workspace_root)):
        return PermissionAction.ALLOW, ""

    return PermissionAction.ASK, f"Path outside allowed zones: {raw_path}"


# ---------------------------------------------------------------------------
# URL Scheme Check — browser_navigate scheme validation (Layer 2)
# ---------------------------------------------------------------------------

_BROWSER_NAVIGATE_PERMISSION = "browser_navigate"
_ALLOWED_NAVIGATE_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_HAS_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")


def _has_explicit_scheme(url: str) -> bool:
    """Return True if *url* has an explicit scheme (``http://``, ``file://``, etc.).

    Bare hostnames with ports (``localhost:3000``) are NOT considered to have
    a scheme. Opaque schemes (``javascript:...``, ``data:...``) are detected
    by checking that the part after ``:`` is not a pure port number.
    """
    if _HAS_SCHEME_RE.match(url):
        return True
    colon = url.find(":")
    if colon <= 0:
        return False
    after_colon = url[colon + 1 :].split("/", 1)[0]
    return not after_colon.isdigit()


def check_navigate_scheme(permission: str, tool_input: dict[str, object]) -> tuple[PermissionAction | None, str]:
    """Validate URL scheme for browser_navigate (Layer 2 Built-in Blacklist).

    Only ``http://`` and ``https://`` are allowed. All other schemes
    (``file://``, ``javascript:``, ``data:``, etc.) are unconditionally
    denied. This check cannot be overridden by user configuration.

    Returns (DENY, reason) if blocked, or (None, "") if clean.
    """
    if permission != _BROWSER_NAVIGATE_PERMISSION:
        return None, ""
    url = str(tool_input.get("url", "")).strip()
    if not url:
        return None, ""
    if not _has_explicit_scheme(url):
        return None, ""
    scheme = urlparse(url).scheme.lower()
    if not scheme:
        return None, ""
    if scheme not in _ALLOWED_NAVIGATE_SCHEMES:
        return PermissionAction.DENY, f"Blocked URL scheme: {scheme}:// (only http/https allowed)"
    return None, ""


# ---------------------------------------------------------------------------
# Shell Command Analyzer — injection vector detection (Layer 2)
# ---------------------------------------------------------------------------

_SHELL_EXEC_PERMISSION = "shell_exec"


def check_shell_threats(permission: str, tool_input: dict[str, object]) -> tuple[PermissionAction | None, str]:
    """Analyze shell commands via shell_command_analyzer (Layer 2).

    Returns (action, reason) if a threat is detected, or (None, "") if clean.
    BLOCK threats → DENY. ESCALATE threats → ASK.
    """
    if permission != _SHELL_EXEC_PERMISSION:
        return None, ""

    from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
        ThreatLevel,
        analyze_command,
    )

    command = str(tool_input.get("command", "") or tool_input.get("code", "")).strip()
    if not command:
        return None, ""

    threats = analyze_command(command)
    if not threats:
        return None, ""

    first = threats[0]
    if first.level == ThreatLevel.BLOCK:
        return PermissionAction.DENY, f"Shell threat [{first.category}]: {first.detail}"
    return PermissionAction.ASK, f"Shell threat [{first.category}]: {first.detail}"
