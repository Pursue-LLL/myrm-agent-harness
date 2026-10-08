"""Explicit User Unlock Workflow for Sensitive Files."""

from __future__ import annotations

import secrets
import threading
from datetime import UTC, datetime, timedelta

from .deny_rules import SensitivePathDenyRules
from .types import FileUnlockGrant


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FileUnlockManager:
    """Manages explicit, temporary user authorization tokens for single-file sensitive mutations."""

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._lock = threading.Lock()
        self._grants: dict[str, FileUnlockGrant] = {}  # token -> grant

    def issue_grant(
        self,
        target_path: str,
        ttl_seconds: int | None = None,
        granted_by: str = "user_explicit_dialog",
    ) -> FileUnlockGrant:
        """Issue an explicit time-bounded unlock token for a specific sensitive file path."""
        norm_path = SensitivePathDenyRules.normalize_path(target_path)
        token = secrets.token_urlsafe(24)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        expires_at = _utc_now() + timedelta(seconds=ttl)

        grant = FileUnlockGrant(
            canonical_path=norm_path,
            unlock_token=token,
            expires_at=expires_at,
            granted_by=granted_by,
        )

        with self._lock:
            self._grants[token] = grant

        return grant

    def validate_grant(self, target_path: str, token: str | None) -> bool:
        """Verify whether an unlock token is valid, unexpired, and matches target path."""
        if not token:
            return False

        norm_path = SensitivePathDenyRules.normalize_path(target_path)

        with self._lock:
            grant = self._grants.get(token)
            if not grant:
                return False

            if grant.is_expired():
                # Cleanup expired token
                self._grants.pop(token, None)
                return False

            return grant.canonical_path == norm_path

    def revoke_grant(self, token: str) -> bool:
        """Revoke an active unlock token."""
        with self._lock:
            return self._grants.pop(token, None) is not None

    def list_active_grants(self) -> list[FileUnlockGrant]:
        """List active unexpired grants."""
        now = _utc_now()
        with self._lock:
            # Filter and prune expired
            valid = [g for g in self._grants.values() if g.expires_at > now]
            self._grants = {g.unlock_token: g for g in valid}
            return valid

    def clear(self) -> None:
        """Clear all active unlock grants."""
        with self._lock:
            self._grants.clear()
