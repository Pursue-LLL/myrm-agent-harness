"""Sensitive Vault and Credential File Overwrite Deny Guard Suite."""

from __future__ import annotations

from .deny_rules import SensitivePathDenyRules
from .sensitive_file_guard import (
    SensitiveVaultAndCredentialFileOverwriteDenyGuard,
)
from .types import (
    FileUnlockGrant,
    FileWriteOperationType,
    PermissionDeniedSensitiveFileError,
    SensitiveFileCategory,
    SensitiveFileDecision,
    SensitiveFileInspection,
    SensitiveFileViolationAlert,
    SensitivePathRule,
)
from .unlock_manager import FileUnlockManager

__all__ = [
    "FileUnlockGrant",
    "FileUnlockManager",
    "FileWriteOperationType",
    "PermissionDeniedSensitiveFileError",
    "SensitiveFileCategory",
    "SensitiveFileDecision",
    "SensitiveFileInspection",
    "SensitiveFileViolationAlert",
    "SensitivePathDenyRules",
    "SensitivePathRule",
    "SensitiveVaultAndCredentialFileOverwriteDenyGuard",
]
