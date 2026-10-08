"""Sensitive directory hard blacklist and system asset protection guard.

[POS] src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/sensitive_blacklist.py
[INPUT] pathlib, os, myrm_agent_harness.core.security.scoped_folder_sandbox_mount.types
[OUTPUT] SensitivePathGuard
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

from myrm_agent_harness.core.security.scoped_folder_sandbox_mount.types import (
    SensitivePathCheckResult,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)

# Canonical sensitive relative subpaths under user home directory
_SENSITIVE_HOME_PATTERNS: tuple[str, ...] = (
    ".ssh",
    ".gnupg",
    ".aws",
    ".kube",
    ".docker",
    ".azure",
    ".config/gcloud",
    "Library/Keychains",
    "AppData/Roaming/Microsoft/Vault",
)

# Canonical system-level root paths prohibited from direct mapping
_SENSITIVE_SYSTEM_PREFIXES: tuple[str, ...] = (
    "/etc",
    "/private/etc",
    "/sys",
    "/proc",
    "/dev",
    "/boot",
    "/var/run",
    "/private/var/run",
    "C:\\Windows",
    "C:\\Program Files",
)


class SensitivePathGuard:
    """Enforces strict hard blacklist avoiding sensitive credential and system OS asset directories."""

    def __init__(self, home_dir: Path | None = None) -> None:
        self._home = (home_dir or Path.home()).resolve()

    def validate_path(self, raw_path: str) -> SensitivePathCheckResult:
        """Evaluate whether a path attempts to project dangerous system or credential directories."""
        try:
            # Expand ~ and environment variables, then resolve symlinks
            expanded = os.path.expanduser(os.path.expandvars(raw_path.strip()))
            resolved = Path(expanded).resolve()
        except Exception as err:
            return SensitivePathCheckResult(
                is_blocked=True,
                resolved_path=raw_path,
                matched_rule="INVALID_PATH_FORMAT",
                reason=f"Path resolution error: {err}",
            )

        resolved_str = str(resolved)

        # 1. Prohibit mapping user home root directly
        if resolved == self._home:
            return SensitivePathCheckResult(
                is_blocked=True,
                resolved_path=resolved_str,
                matched_rule="HOME_ROOT_PROHIBITED",
                reason="Direct mapping of entire user home directory is prohibited for privacy protection.",
            )

        # 2. Prohibit root filesystem mapping
        if resolved == Path("/").resolve():
            return SensitivePathCheckResult(
                is_blocked=True,
                resolved_path=resolved_str,
                matched_rule="FILESYSTEM_ROOT_PROHIBITED",
                reason="Direct mapping of root filesystem is strictly prohibited.",
            )

        # 3. Check system-level dangerous prefixes
        norm_raw = raw_path.strip()
        for prefix in _SENSITIVE_SYSTEM_PREFIXES:
            if norm_raw.startswith(prefix) or resolved_str.startswith(prefix):
                return SensitivePathCheckResult(
                    is_blocked=True,
                    resolved_path=resolved_str,
                    matched_rule=f"SYSTEM_PREFIX:{prefix}",
                    reason=f"Path touches protected operating system infrastructure ({prefix}).",
                )

        # 4. Check sensitive user credential directories
        for pattern in _SENSITIVE_HOME_PATTERNS:
            forbidden_target = (self._home / pattern).resolve()
            # If resolved path is the forbidden folder or inside it
            if resolved == forbidden_target or forbidden_target in resolved.parents:
                return SensitivePathCheckResult(
                    is_blocked=True,
                    resolved_path=resolved_str,
                    matched_rule=f"CREDENTIAL_ASSET:{pattern}",
                    reason=f"Path accesses sensitive credential vault (~/{pattern}).",
                )

        return SensitivePathCheckResult(
            is_blocked=False,
            resolved_path=resolved_str,
            matched_rule=None,
            reason=None,
        )
