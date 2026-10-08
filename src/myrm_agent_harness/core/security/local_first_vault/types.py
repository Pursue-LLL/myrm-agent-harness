"""Data models and schemas for Local-First Zero-Leak Vault and E2EE Sharing Gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class VaultStorageMode(StrEnum):
    """Storage location classification enforcing local-first invariant."""

    LOCAL_FIRST_DISK = "local_first_disk"
    SANDBOX_VOLUME = "sandbox_volume"
    ENCRYPTED_COLLABORATIVE = "encrypted_collaborative"


class DlpSensitivityCategory(StrEnum):
    """Category classification for DLP detected sensitive content."""

    INTERNAL_IP = "internal_ip"
    INTERNAL_DOMAIN = "internal_domain"
    SECRET_TOKEN = "secret_token"
    PHONE_NUMBER = "phone_number"
    COMMERCIAL_PRICE = "commercial_price"


@dataclass(frozen=True, slots=True)
class DlpRedactionMatch:
    """Individual sensitive element detected and sanitized by DLP scanner."""

    category: DlpSensitivityCategory
    original_snippet: str
    redacted_snippet: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class DlpRedactionResult:
    """Outcome of transparent DLP scanning and sanitization pipeline."""

    original_length: int
    redacted_length: int
    total_redactions: int
    categories_found: list[DlpSensitivityCategory]
    matches: list[DlpRedactionMatch]
    sanitized_content: str


@dataclass(frozen=True, slots=True)
class E2eeShareEnvelope:
    """Zero-knowledge encrypted artifact sharing envelope."""

    share_id: str
    artifact_id: str
    ciphertext_b64: str
    nonce_b64: str
    salt_b64: str
    key_hash: str
    dlp_audit_passed: bool
    expires_at: datetime
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class LocalVaultItem:
    """Metadata for an artifact stored under the local-first physical storage invariant."""

    artifact_id: str
    title: str
    local_path: str
    storage_mode: VaultStorageMode
    is_cloud_synced: bool
    content_hash: str
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
