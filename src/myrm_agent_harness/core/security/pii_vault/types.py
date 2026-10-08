"""Type definitions for Client-Side PII Auto-Sanitization and Local Mapping Vault.

[INPUT]
None.

[OUTPUT]
- PiiEntityType, PiiEntityMatch, SanitizationResult, DesanitizationResult
- PiiVaultError, EntityDetectionError

[POS]
Harness core security subsystem for client-side privacy preservation and reversible pseudonymization.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class PiiEntityType(StrEnum):
    """Supported personally identifiable information (PII) entity types."""

    CHINESE_NAME = "chinese_name"
    PHONE_NUMBER = "phone_number"
    ID_CARD = "id_card"
    EMAIL = "email"
    BANK_CARD = "bank_card"
    STUDENT_ID = "student_id"


@dataclass(frozen=True, slots=True)
class PiiEntityMatch:
    """Individual detected PII entity with string boundary coordinates."""

    entity_type: PiiEntityType
    raw_value: str
    placeholder: str
    start_idx: int
    end_idx: int


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    """Outcome of transparent pseudonymization transformation."""

    sanitized_text: str
    placeholders_count: int
    entities_detected: tuple[PiiEntityMatch, ...]
    session_id: str
    sanitized_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class DesanitizationResult:
    """Outcome of reverse mapping reconstruction."""

    restored_text: str
    restored_count: int
    placeholders_found: tuple[str, ...]
    session_id: str
    restored_at: float = field(default_factory=time.time)


class PiiVaultError(Exception):
    """Base error for PII vault operations."""


class EntityDetectionError(PiiVaultError):
    """Raised when PII detection encounters parsing abnormalities."""
