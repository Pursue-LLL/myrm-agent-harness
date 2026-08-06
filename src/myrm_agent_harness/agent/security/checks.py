"""Built-in security checks — Layer 2 & 2.5 of the onion security architecture.

Path policy evaluation, URL scheme validation, and shell threat analysis.
All checks are pure functions — no side effects, no I/O, trivially testable.


[POS]
See module docstring.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from myrm_agent_harness.agent.security.path_security import is_sensitive_file
from myrm_agent_harness.agent.security.types import PathPolicy, PermissionAction

# ---------------------------------------------------------------------------
# Path Policy — forbidden/access path zones for file operations (Layer 2.5)
# ---------------------------------------------------------------------------


def _normalize_path(raw: str) -> str:
    """Expand ~ and $HOME, resolve to absolute path for comparison."""
    return os.path.realpath(os.path.expanduser(os.path.expandvars(raw)))


def _is_subpath(child: str, parent: str) -> bool:
    """Check if child path is equal to or under parent directory."""
    return child == parent or child.startswith(parent + os.sep)


def check_path_policy(
    raw_path: str,
    policy: PathPolicy,
    workspace_root: str | None,
    *,
    require_write: bool = False,
) -> tuple[PermissionAction, str]:
    """Evaluate a file path against the PathPolicy.

    Returns (DENY, reason) if blocked by forbidden paths.
    Returns (ALLOW, "") if in a writable access root or workspace (when writing).
    Returns (ALLOW, "") for read-only roots when require_write is False.
    Returns (DENY, reason) for write attempts on read-only roots.
    Returns (ASK, reason) if outside allowed zones, requiring user approval or
    request_directory_tool.
    Relative paths are resolved against workspace_root when available.
    """
    if workspace_root and not os.path.isabs(os.path.expanduser(raw_path)):
        normalized = _normalize_path(os.path.join(workspace_root, raw_path))
    else:
        normalized = _normalize_path(raw_path)

    for fp in policy.forbidden_paths:
        if _is_subpath(normalized, _normalize_path(fp)):
            return PermissionAction.DENY, f"Path in forbidden zone: {raw_path}"

    matched_writable = False
    matched_readonly = False

    for root in policy.access_roots:
        root_norm = _normalize_path(root.path)
        if _is_subpath(normalized, root_norm):
            if root.writable:
                matched_writable = True
            else:
                matched_readonly = True

    if (
        workspace_root
        and _is_subpath(normalized, _normalize_path(workspace_root))
    ):
        matched_writable = True

    if matched_writable:
        if is_sensitive_file(raw_path):
            return PermissionAction.ASK, f"Sensitive file: {os.path.basename(raw_path)}"
        return PermissionAction.ALLOW, ""

    if matched_readonly:
        if require_write:
            return (
                PermissionAction.DENY,
                f"Path is read-only: {raw_path} (use request_directory_tool for write access)",
            )
        if is_sensitive_file(raw_path):
            return PermissionAction.ASK, f"Sensitive file: {os.path.basename(raw_path)}"
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


def check_navigate_scheme(
    permission: str, tool_input: dict[str, object]
) -> tuple[PermissionAction | None, str]:
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
        return (
            PermissionAction.DENY,
            f"Blocked URL scheme: {scheme}:// (only http/https allowed)",
        )
    return None, ""


# ---------------------------------------------------------------------------
# Shell Command Analyzer — injection vector detection (Layer 2)
# ---------------------------------------------------------------------------

_SHELL_EXEC_PERMISSION = "shell_exec"


def check_shell_threats(
    permission: str, tool_input: dict[str, object]
) -> tuple[PermissionAction | None, str]:
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

    command = str(
        tool_input.get("command", "")
        or tool_input.get("code", "")
        or tool_input.get("data", "")
    ).strip()
    if not command:
        return None, ""

    threats = analyze_command(command)
    if not threats:
        return None, ""

    first = threats[0]
    if first.level == ThreatLevel.BLOCK:
        return PermissionAction.DENY, f"Shell threat [{first.category}]: {first.detail}"
    return PermissionAction.ASK, f"Shell threat [{first.category}]: {first.detail}"
