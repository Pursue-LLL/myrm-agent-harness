"""Credential file validator — workspace boundary checks for skill credentials.

Validates credential file paths declared in skill frontmatter, ensuring they:
- Stay within workspace boundaries (no path traversal)
- Resolve symlinks safely (no escape via symlink)
- Have read permissions
- Exist on the file system

[INPUT]
- types::SkillMetadata (POS: skill metadata with required_credential_files)
- pathlib::Path (stdlib: path operations)

[OUTPUT]
- CredentialValidator: validates credential files with caching
- CredentialValidationResult: validation result with valid/missing lists

[POS]
Dedicated validator for credential files. Simpler than full file_ops validators
because credentials only need existence + boundary checks, not full ACL evaluation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from time import time

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL = 60  # seconds


@dataclass(frozen=True, slots=True)
class CredentialValidationResult:
    """Result of credential file validation."""

    valid_files: list[str]
    """List of valid credential files (relative paths)"""

    missing_files: list[str]
    """List of missing/invalid credential files with reasons"""


class CredentialValidator:
    """Validates credential files for workspace boundary and readability.

    Uses caching (60s TTL) to avoid repeated filesystem checks for the same files.
    Per-user sandbox architecture means no cross-session isolation needed.
    """

    def __init__(self, workspace_root: Path, cache_ttl: int = _DEFAULT_CACHE_TTL) -> None:
        """Initialize validator.

        Args:
            workspace_root: Absolute path to workspace root
            cache_ttl: Cache TTL in seconds (default 60s)
        """
        self._workspace_root = workspace_root.resolve()
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[bool, str, float]] = {}
        # cache key: relative_path -> (is_valid, reason, timestamp)

    def validate_credential_files(self, files: list[str]) -> CredentialValidationResult:
        """Validate credential file list.

        Args:
            files: List of credential file paths (relative to workspace)

        Returns:
            CredentialValidationResult with valid and missing file lists
        """
        valid_files: list[str] = []
        missing_files: list[str] = []

        for rel_path in files:
            is_valid, reason = self._validate_single_file(rel_path)
            if is_valid:
                valid_files.append(rel_path)
            else:
                missing_files.append(f"{rel_path} ({reason})")

        return CredentialValidationResult(
            valid_files=valid_files,
            missing_files=missing_files,
        )

    def _validate_single_file(self, rel_path: str) -> tuple[bool, str]:
        """Validate a single credential file.

        Returns:
            (is_valid, reason) - reason is empty string if valid
        """
        # Check cache first
        if rel_path in self._cache:
            is_valid, reason, cached_at = self._cache[rel_path]
            if time() - cached_at < self._cache_ttl:
                return is_valid, reason

        # 1. Reject absolute paths
        if os.path.isabs(rel_path):
            reason = "absolute path not allowed"
            self._cache[rel_path] = (False, reason, time())
            return False, reason

        # 2. Resolve path (resolves symlinks and normalizes ..)
        try:
            resolved = (self._workspace_root / rel_path).resolve()
        except (OSError, RuntimeError) as e:
            reason = f"path resolution failed: {e}"
            self._cache[rel_path] = (False, reason, time())
            return False, reason

        # 3. Workspace boundary check (prevent path traversal)
        try:
            resolved.relative_to(self._workspace_root)
        except ValueError:
            reason = "path traversal detected (outside workspace)"
            self._cache[rel_path] = (False, reason, time())
            logger.warning(
                "Credential file %r traverses outside workspace. Resolved to: %s, Workspace: %s",
                rel_path,
                resolved,
                self._workspace_root,
            )
            return False, reason

        # 4. File existence check
        if not resolved.is_file():
            reason = "file not found"
            self._cache[rel_path] = (False, reason, time())
            return False, reason

        # 5. Read permission check
        if not os.access(resolved, os.R_OK):
            reason = "file not readable (permission denied)"
            self._cache[rel_path] = (False, reason, time())
            return False, reason

        # All checks passed
        self._cache[rel_path] = (True, "", time())
        return True, ""

    def clear_cache(self) -> None:
        """Clear validation cache (useful for testing or manual refresh)."""
        self._cache.clear()
