"""Cloud sandbox privacy fail-closed ladder validator.

[INPUT]
- myrm_agent_harness.core.security.path_security::is_sensitive_file (POS: Sensitive file patterns check)
- myrm_agent_harness.core.security.path_security::is_within_boundary (POS: Symlink-immune workspace boundary check)
- myrm_agent_harness.core.security.path_security::is_dangerous_path (POS: System dangerous roots check)
- myrm_agent_harness.core.security.path_security::is_blocked_device_path (POS: Blocked device path check)

[OUTPUT]
- PrivacyLadderLevel: Enum for ladder level (FILE_LEVEL, SESSION_LEVEL, WORKSPACE_LEVEL)
- PrivacyScanVerdict: PASS or FAIL_CLOSED
- PrivacyLadderViolation: Dataclass recording violation details (level, path, reason)
- PrivacyLadderValidator: Validator applying the 3-level fail-closed privacy ladder to paths & artifacts

[POS]
Harness core security module for cloud sandbox privacy boundary validation.
Pure domain logic, strictly fail-closed, zero coupling to cloud/multi-tenant platforms.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path

from myrm_agent_harness.core.security.path_security import (
    is_blocked_device_path,
    is_dangerous_path,
    is_sensitive_file,
    is_within_boundary,
)

# Common ephemeral cache & build patterns to ignore during persistence
DEFAULT_IGNORE_DIR_PATTERNS: tuple[str, ...] = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".npm",
    ".yarn",
    ".cache",
    ".temp",
    ".tmp",
    ".venv",
    "venv",
    ".git",
)

DEFAULT_IGNORE_FILE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*.swo",
    "*~",
)


class PrivacyLadderLevel(StrEnum):
    """The 3-level defense ladder for cloud sandbox privacy."""

    FILE_LEVEL = "file_level"  # Level 1: credentials, secrets, dangerous system paths
    SESSION_LEVEL = "session_level"  # Level 2: session isolation & cross-session leakage
    WORKSPACE_LEVEL = "workspace_level"  # Level 3: sandbox root & symlink escape


class PrivacyScanVerdict(StrEnum):
    PASS = "pass"
    FAIL_CLOSED = "fail_closed"
    IGNORED = "ignored"  # Ephemeral / cache artifact, safe to skip


@dataclass(frozen=True)
class PrivacyLadderViolation:
    """Diagnostic detail for a fail-closed privacy violation."""

    level: PrivacyLadderLevel
    path: str
    reason: str


@dataclass(frozen=True)
class PrivacyLadderScanResult:
    """Result of evaluating a path against the 3-level privacy ladder."""

    verdict: PrivacyScanVerdict
    sanitized_rel_path: str | None = None
    violations: list[PrivacyLadderViolation] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return self.verdict == PrivacyScanVerdict.PASS

    @property
    def is_ignored(self) -> bool:
        return self.verdict == PrivacyScanVerdict.IGNORED


class PrivacyLadderValidator:
    """Pure-logic 3-level fail-closed privacy ladder validator for sandbox persistence."""

    def __init__(
        self,
        workspace_root: str | Path,
        session_id: str | None = None,
        custom_ignore_dirs: tuple[str, ...] = DEFAULT_IGNORE_DIR_PATTERNS,
        custom_ignore_files: tuple[str, ...] = DEFAULT_IGNORE_FILE_PATTERNS,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.session_id = session_id.strip() if session_id else None
        self.ignore_dirs = custom_ignore_dirs
        self.ignore_files = custom_ignore_files

    def is_ignored_path(self, target_path: str | Path) -> bool:
        """Check if path is a transient cache/build directory or file."""
        p = Path(target_path)
        parts = p.parts
        for part in parts:
            if any(fnmatch(part, pattern) for pattern in self.ignore_dirs):
                return True
        name = p.name
        return any(fnmatch(name, pattern) for pattern in self.ignore_files)

    def evaluate_path(self, target_path: str | Path) -> PrivacyLadderScanResult:
        """Evaluate a target file path against the 3-level fail-closed privacy ladder.

        Level 3 (Workspace Root):
          Must be strictly within workspace_root (immune to symlink escape and ../ traversal).
        Level 2 (Session Isolation):
          If target is nested in another session subfolder, fail-closed unless matching self.session_id.
        Level 1 (File/Secret Level):
          Cannot match dangerous roots, blocked devices, or sensitive credential files (.env, keys, etc.).
        """
        raw_str = str(target_path).strip()
        if not raw_str:
            return PrivacyLadderScanResult(
                verdict=PrivacyScanVerdict.FAIL_CLOSED,
                violations=[
                    PrivacyLadderViolation(
                        level=PrivacyLadderLevel.FILE_LEVEL,
                        path="",
                        reason="Empty target path",
                    )
                ],
            )

        # 0. Check if it's transient cache to be cleanly ignored
        if self.is_ignored_path(target_path):
            return PrivacyLadderScanResult(
                verdict=PrivacyScanVerdict.IGNORED,
                sanitized_rel_path=None,
            )

        violations: list[PrivacyLadderViolation] = []

        # --- LEVEL 3: Workspace Boundary & Symlink Escape ---
        # Note: If path is relative, resolve against workspace_root
        p = Path(target_path)
        abs_p = (self.workspace_root / p).resolve() if not p.is_absolute() else p.resolve()

        if not is_within_boundary(abs_p, self.workspace_root):
            violations.append(
                PrivacyLadderViolation(
                    level=PrivacyLadderLevel.WORKSPACE_LEVEL,
                    path=raw_str,
                    reason=f"Path '{raw_str}' escapes workspace root '{self.workspace_root}'",
                )
            )

        # --- LEVEL 2: Session Isolation ---
        # If relative path contains sessions/<other_session_id>, prevent cross-session exfiltration
        try:
            rel_p = abs_p.relative_to(self.workspace_root)
            rel_parts = rel_p.parts
            if "sessions" in rel_parts:
                idx = rel_parts.index("sessions")
                if idx + 1 < len(rel_parts):
                    target_session = rel_parts[idx + 1]
                    if self.session_id and target_session != self.session_id:
                        violations.append(
                            PrivacyLadderViolation(
                                level=PrivacyLadderLevel.SESSION_LEVEL,
                                path=raw_str,
                                reason=f"Cross-session access forbidden: target session '{target_session}' != current '{self.session_id}'",
                            )
                        )
            sanitized_rel = str(rel_p)
        except ValueError:
            sanitized_rel = None

        # --- LEVEL 1: File & Secret Level ---
        if is_dangerous_path(raw_str) or is_dangerous_path(str(abs_p)):
            violations.append(
                PrivacyLadderViolation(
                    level=PrivacyLadderLevel.FILE_LEVEL,
                    path=raw_str,
                    reason=f"Path '{raw_str}' is within a dangerous system root",
                )
            )

        if is_blocked_device_path(raw_str) or is_blocked_device_path(str(abs_p)):
            violations.append(
                PrivacyLadderViolation(
                    level=PrivacyLadderLevel.FILE_LEVEL,
                    path=raw_str,
                    reason=f"Path '{raw_str}' refers to a blocked character/device path",
                )
            )

        if is_sensitive_file(raw_str) or is_sensitive_file(str(abs_p)):
            violations.append(
                PrivacyLadderViolation(
                    level=PrivacyLadderLevel.FILE_LEVEL,
                    path=raw_str,
                    reason=f"File '{raw_str}' matches sensitive credential/secret patterns (.env, keys, etc.)",
                )
            )

        if violations:
            return PrivacyLadderScanResult(
                verdict=PrivacyScanVerdict.FAIL_CLOSED,
                sanitized_rel_path=None,
                violations=violations,
            )

        return PrivacyLadderScanResult(
            verdict=PrivacyScanVerdict.PASS,
            sanitized_rel_path=sanitized_rel,
            violations=[],
        )
