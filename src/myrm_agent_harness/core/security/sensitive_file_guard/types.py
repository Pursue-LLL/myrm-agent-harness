"""Data types and schemas for Sensitive Vault and Credential File Overwrite Deny Guard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class SensitiveFileCategory(StrEnum):
    """Classification of protected sensitive credential and vault files."""

    ENV_SECRET = "env_secret"
    PRIVATE_KEY = "private_key"
    PASSWORD_VAULT = "password_vault"
    CLOUD_CREDENTIAL = "cloud_credential"
    OAUTH_CACHE = "oauth_cache"
    SYSTEM_AUTH = "system_auth"


class FileWriteOperationType(StrEnum):
    """File mutation action kinds intercepted by the guard."""

    WRITE = "write"
    OVERWRITE = "overwrite"
    APPEND = "append"
    REPLACE = "replace"
    DELETE = "delete"
    TRUNCATE = "truncate"


class PermissionDeniedSensitiveFileError(Exception):
    """Raised when an operation attempts unauthorized mutation of a sensitive file."""


@dataclass(frozen=True, slots=True)
class SensitivePathRule:
    """Pattern rule designating files and directories under immutable write protection."""

    rule_id: str
    pattern: str
    category: SensitiveFileCategory
    description: str
    is_regex: bool = False


@dataclass(frozen=True, slots=True)
class FileUnlockGrant:
    """Temporary explicit user authorization granting write access to a sensitive path."""

    canonical_path: str
    unlock_token: str
    expires_at: datetime
    granted_by: str = "user_explicit_dialog"

    def is_expired(self) -> bool:
        """Check if this unlock grant has passed its TTL."""
        return _utc_now() > self.expires_at


@dataclass(frozen=True, slots=True)
class SensitiveFileInspection:
    """Submitted file mutation operation inspected by the security guard."""

    target_path: str
    operation_type: FileWriteOperationType = FileWriteOperationType.OVERWRITE
    tool_name: str = "file_write"
    session_id: str = "default_session"
    unlock_token: str | None = None


@dataclass(frozen=True, slots=True)
class SensitiveFileDecision:
    """Outcome of sensitive file overwrite inspection."""

    allowed: bool
    matched_rule: SensitivePathRule | None
    reason: str
    is_unlocked: bool = False


@dataclass(frozen=True, slots=True)
class SensitiveFileViolationAlert:
    """Audit log entry recorded when a write to a sensitive file is blocked."""

    alert_id: str
    session_id: str
    target_path: str
    category: SensitiveFileCategory
    operation_type: FileWriteOperationType
    tool_name: str
    reason: str
    timestamp: datetime = field(default_factory=_utc_now)
