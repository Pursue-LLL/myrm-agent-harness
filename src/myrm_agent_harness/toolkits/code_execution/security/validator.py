"""Unified security validator for code execution.

Validates:
- Python module imports
- Bash command execution (delegates to shell_command_analyzer for threat detection)
- File path access

All checks return a ``ValidationResult`` with structured error information.

Path security uses FORBIDDEN_PATHS as a last line of defense.
The primary path policy enforcement happens in the Permission Engine layer;
this validator provides defense-in-depth for the local code executor.

[INPUT]
- (none)

[OUTPUT]
- ValidationResult: Validation result.
- EnvInheritPolicy: Environment variable inheritance strategy for subprocess ...
- validate_module: Validate whether a Python module import is safe.
- is_module_allowed: Check if a module import is allowed (convenience wrapper).
- validate_command: Validate a Bash command for security (session-isolated).

[POS]
Unified security validator for code execution.
"""

import logging
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from myrm_agent_harness.toolkits.code_execution.security.blacklist import (
    CORE_SAFE_ENV_VARS,
    DANGEROUS_ENV_PREFIXES,
    DANGEROUS_ENV_VARS,
    DANGEROUS_ENV_WILDCARDS,
    DANGEROUS_MODULES,
    DANGEROUS_MODULES_REASONS,
)
from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
    ThreatLevel,
)
from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
    analyze_command as _analyze_shell_threats,
)

FORBIDDEN_PATHS: frozenset[str] = frozenset(
    {
        "~/.ssh",
        "~/.gnupg",
        "~/.gpg",
        "~/.aws",
        "~/.config/gcloud",
        "~/.azure",
        "/etc/shadow",
        "/etc/passwd",
        "/proc",
        "/sys",
    }
)


def _is_forbidden_path(path_str: str) -> bool:
    """Check if a path falls under any FORBIDDEN_PATHS entry."""
    normalized = os.path.realpath(os.path.expanduser(os.path.expandvars(path_str)))
    for fp in FORBIDDEN_PATHS:
        normalized_fp = os.path.realpath(os.path.expanduser(os.path.expandvars(fp)))
        if normalized == normalized_fp or normalized.startswith(normalized_fp + os.sep):
            return True
    return False


@dataclass
class ValidationResult:
    """Validation result."""

    is_safe: bool
    reason: str | None = None
    blocked_item: str | None = None


# ============================================================
# Module validation
# ============================================================


def validate_module(module_name: str) -> ValidationResult:
    """Validate whether a Python module import is safe.

    Args:
        module_name: Module name to validate.

    Returns:
        ValidationResult with validation outcome.
    """
    main_module = module_name.split(".")[0]

    if module_name in DANGEROUS_MODULES:
        return ValidationResult(
            is_safe=False,
            reason=DANGEROUS_MODULES_REASONS.get(module_name, "Security risk"),
            blocked_item=module_name,
        )

    if main_module in DANGEROUS_MODULES:
        return ValidationResult(
            is_safe=False,
            reason=DANGEROUS_MODULES_REASONS.get(main_module, "Security risk"),
            blocked_item=main_module,
        )

    return ValidationResult(is_safe=True)


def is_module_allowed(module_name: str) -> bool:
    """Check if a module import is allowed (convenience wrapper)."""
    return validate_module(module_name).is_safe


# ============================================================
# Command validation
# ============================================================

# Regex to extract paths from commands (supports ~, $HOME, absolute, and .. relative paths)
_PATH_PATTERN = re.compile(
    r"""
    (?:^|\s)                    # start or whitespace
    (
        ~(?:/[^\s;|&><"']*)?    # ~ or ~/xxx
        |
        \$HOME(?:/[^\s;|&><"']*)? # $HOME or $HOME/xxx
        |
        /[^\s;|&><"']+          # absolute path
        |
        \.\.(?:/[^\s;|&><"']*)?  # relative path starting with ..
        |
        [^\s;|&><"']*(?:/\.\.)[^\s;|&><"']*  # any path containing /.. (traversal)
    )
    """,
    re.VERBOSE,
)


def _get_allowed_paths(
    workspace_path: Path | None = None,
    additional_paths: list[Path] | None = None,
) -> list[Path]:
    """Build the list of allowed paths (strict session isolation).

    Allows access to:
    1. Current session workspace directory
    2. Explicitly allowed additional paths (e.g. skill directories)
    3. /workspace (container-isolated)
    4. /tmp (temporary files)

    Args:
        workspace_path: Current session workspace directory.
        additional_paths: Extra allowed paths.

    Returns:
        List of allowed paths.
    """
    allowed: list[Path] = []

    if workspace_path:
        allowed.append(workspace_path.resolve())

    if additional_paths:
        for path in additional_paths:
            allowed.append(path.resolve())

    allowed.append(Path("/workspace"))
    allowed.append(Path("/tmp"))
    allowed.append(Path("/persistent/.context"))

    return allowed


def _is_path_allowed(path_str: str, allowed_paths: list[Path]) -> bool:
    """Check if a path is within allowed zones (whitelist + forbidden check).

    Rules:
    1. Forbidden paths (FORBIDDEN_PATHS) → always denied
    2. Relative path without .. → safe (within workspace)
    3. Absolute or .. path → must be under an allowed directory
    """
    if _is_forbidden_path(path_str):
        return False

    try:
        path = Path(path_str)

        if not path.is_absolute() and ".." not in path_str:
            return True

        resolved = path.resolve()

        for allowed in allowed_paths:
            allowed_resolved = allowed.resolve()
            try:
                resolved.relative_to(allowed_resolved)
                return True
            except ValueError:
                continue

        return False
    except Exception:
        return False


def _extract_paths(command: str) -> list[str]:
    """Extract file paths from a command string."""
    paths: list[str] = []
    for match in _PATH_PATTERN.finditer(command):
        path = match.group(1).strip()
        if path:
            paths.append(path)
    return paths


# Regex to extract URLs from commands (curl/wget etc.)
_URL_PATTERN = re.compile(
    r"""
    (?:https?|ftp)://       # protocol
    (?:[^\s\"'<>]+)          # rest of URL (no whitespace or quotes)
    """,
    re.VERBOSE,
)


def _extract_url_hosts(command: str) -> list[str]:
    """Extract target hostnames from URLs in a command.

    Handles IPv4/IPv6, user:pass@host, port numbers, and URL encoding
    via urllib.parse.

    Args:
        command: Command string.

    Returns:
        List of hostnames.
    """
    hosts: list[str] = []

    for match in _URL_PATTERN.finditer(command):
        url = match.group(0)
        try:
            parsed = urlparse(url)
            if parsed.netloc:
                netloc = parsed.netloc.split("@")[-1]

                if netloc.startswith("["):
                    # IPv6: [::1]:8000 -> ::1
                    host = netloc.split("]")[0][1:]
                else:
                    # IPv4/domain: example.com:8000 -> example.com
                    host = netloc.split(":")[0]

                if host:
                    hosts.append(host)
        except Exception:
            continue

    return hosts


def validate_command(
    command: str,
    workspace_path: Path | None = None,
    additional_paths: list[Path] | None = None,
    check_paths: bool = True,
    allowed_hosts: frozenset[str] | None = None,
) -> ValidationResult:
    """Validate a Bash command for security (session-isolated).

    Security layers:
    1. Shell Command Analyzer (injection vectors + dangerous patterns)
    2. Path whitelist — only session workspace and explicitly allowed paths
    3. Host whitelist — restrict curl/wget targets if configured

    Args:
        command: command string to validate
        workspace_path: session workspace directory
        additional_paths: extra allowed paths (e.g. skill directories)
        check_paths: whether to enforce path restrictions (default True)
        allowed_hosts: host whitelist (None=no check, empty=block all network)

    Returns:
        ValidationResult with structured error information
    """
    threats = _analyze_shell_threats(command)
    for threat in threats:
        if threat.level == ThreatLevel.BLOCK:
            return ValidationResult(
                is_safe=False,
                reason=f"{threat.detail} ({threat.evidence})",
                blocked_item=threat.evidence,
            )

    normalized_cmd = " ".join(command.split())
    if check_paths:
        paths = _extract_paths(normalized_cmd)

        if paths:
            allowed_paths = _get_allowed_paths(workspace_path, additional_paths)

            for path in paths:
                if not _is_path_allowed(path, allowed_paths):
                    return ValidationResult(
                        is_safe=False,
                        reason=f"Access denied: {path}. Only current session workspace is accessible.",
                        blocked_item=path,
                    )

    # Host whitelist check for network access
    if allowed_hosts is not None:
        url_hosts = _extract_url_hosts(normalized_cmd)

        if url_hosts:
            for host in url_hosts:
                if host not in allowed_hosts:
                    return ValidationResult(
                        is_safe=False,
                        reason=f"Network access to '{host}' is blocked. Allowed hosts: {', '.join(sorted(allowed_hosts))}",
                        blocked_item=host,
                    )

    return ValidationResult(is_safe=True)


def is_command_allowed(command: str) -> bool:
    """Check if a command is allowed (convenience wrapper)."""
    return validate_command(command).is_safe


# ============================================================
# Path validation
# ============================================================


def validate_path(
    path: str | Path,
    allowed_dirs: list[Path] | None = None,
    mode: str = "read",
) -> ValidationResult:
    """Validate file path access (whitelist + forbidden check).

    Security layers:
    1. FORBIDDEN_PATHS hard-block (defense-in-depth)
    2. Relative path without .. → safe
    3. Absolute/.. path → must be under allowed_dirs
    """
    path_str = str(path)
    path_obj = Path(path) if isinstance(path, str) else path

    if _is_forbidden_path(path_str):
        return ValidationResult(
            is_safe=False,
            reason=f"Access denied: {path}. Path is in a forbidden security zone.",
            blocked_item=path_str,
        )

    if allowed_dirs is None:
        allowed_dirs = _get_allowed_paths()

    if not path_obj.is_absolute() and ".." not in path_str:
        return ValidationResult(is_safe=True)

    try:
        abs_path = path_obj.resolve()

        for allowed in allowed_dirs:
            allowed_resolved = allowed.resolve()
            try:
                abs_path.relative_to(allowed_resolved)
                return ValidationResult(is_safe=True)
            except ValueError:
                continue
    except (OSError, RuntimeError, ValueError) as e:
        return ValidationResult(
            is_safe=False,
            reason=f"Cannot resolve path {path}: {e}",
            blocked_item=path_str,
        )

    return ValidationResult(
        is_safe=False,
        reason=f"Access denied ({mode}): {path}. Only workspace directory is accessible.",
        blocked_item=path_str,
    )


def is_path_allowed(path: str | Path, mode: str = "read") -> bool:
    """Check if a path is allowed (convenience wrapper)."""
    return validate_path(path, mode=mode).is_safe


# ============================================================
# Path component validation (for user_id, chat_id, etc.)
# ============================================================


def validate_path_component(
    component: str, component_name: str = "path component"
) -> ValidationResult:
    """Validate a path component for safety (user_id, chat_id, workspace_id, etc.).

    Prevents path traversal attacks and filesystem restriction bypass.

    Args:
        component: Path component to validate.
        component_name: Component name for error messages.

    Returns:
        ValidationResult with validation outcome.

    Rules:
    - Only alphanumeric, hyphen (-), underscore (_) allowed
    - No path separators (/, \\)
    - No path traversal (..)
    - Cannot start with dot (hidden files)
    - Length: 1-255 characters
    """
    if not component:
        return ValidationResult(
            is_safe=False,
            reason=f"Invalid {component_name}: empty value",
            blocked_item=component,
        )

    if len(component) > 255:
        return ValidationResult(
            is_safe=False,
            reason=f"Invalid {component_name}: exceeds maximum length (255 characters)",
            blocked_item=component,
        )

    if component.startswith("."):
        return ValidationResult(
            is_safe=False,
            reason=f"Invalid {component_name}: cannot start with '.'",
            blocked_item=component,
        )

    if ".." in component:
        return ValidationResult(
            is_safe=False,
            reason=f"Invalid {component_name}: contains path traversal pattern '..'",
            blocked_item=component,
        )

    if "/" in component or "\\" in component:
        return ValidationResult(
            is_safe=False,
            reason=f"Invalid {component_name}: contains path separator",
            blocked_item=component,
        )

    if not re.match(r"^[a-zA-Z0-9_-]+$", component):
        return ValidationResult(
            is_safe=False,
            reason=f"Invalid {component_name}: contains invalid characters (only alphanumeric, '-', '_' allowed)",
            blocked_item=component,
        )

    return ValidationResult(is_safe=True)


def is_path_component_safe(
    component: str, component_name: str = "path component"
) -> bool:
    """Check if a path component is safe (convenience wrapper)."""
    return validate_path_component(component, component_name).is_safe


# ============================================================
# Environment variable sanitization
# ============================================================


_env_logger = logging.getLogger(__name__)


class EnvInheritPolicy(StrEnum):
    """Environment variable inheritance strategy for subprocess execution.

    ALL: Inherit all env vars, filter only dangerous ones (default).
    CORE: Only inherit CORE_SAFE_ENV_VARS, filter everything else.
    NONE: Pass no env vars at all (strictest isolation).
    """

    ALL = "all"
    CORE = "core"
    NONE = "none"


def _matches_wildcard(key: str) -> bool:
    """Check if env var name contains any dangerous wildcard pattern."""
    upper = key.upper()
    return any(w in upper for w in DANGEROUS_ENV_WILDCARDS)


def sanitize_env(
    env: dict[str, str],
    inherit_policy: EnvInheritPolicy = EnvInheritPolicy.ALL,
) -> dict[str, str]:
    """Filter environment variables based on security policy.

    Policies:
    - ALL: Inherit all vars, filter dangerous ones (exact + prefix + wildcard).
    - CORE: Only keep CORE_SAFE_ENV_VARS, reject everything else.
    - NONE: Return empty dict (strictest isolation).

    Args:
        env: Original environment variables dictionary.
        inherit_policy: Inheritance strategy (default: ALL).

    Returns:
        Sanitized environment variables dictionary.
    """
    if inherit_policy == EnvInheritPolicy.NONE:
        return {}

    filtered: dict[str, str] = {}
    blocked: list[str] = []

    for key, value in env.items():
        if inherit_policy == EnvInheritPolicy.CORE:
            if key not in CORE_SAFE_ENV_VARS:
                blocked.append(key)
                continue
            filtered[key] = value
            continue

        if key in DANGEROUS_ENV_VARS or key.startswith(DANGEROUS_ENV_PREFIXES):
            blocked.append(key)
            continue
        if _matches_wildcard(key):
            blocked.append(key)
            continue
        filtered[key] = value

    if blocked:
        _env_logger.info(
            f" Blocked {len(blocked)} env vars ({inherit_policy}): {', '.join(sorted(blocked))}"
        )

    return filtered
