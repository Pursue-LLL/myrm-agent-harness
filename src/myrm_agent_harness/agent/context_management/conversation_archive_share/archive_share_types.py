# [INPUT]: None
# [OUTPUT]: ArchiveTier, ColdArchiveRecord, ConversationArchiveShareConfig, SanitizedShareMessage, ShareAccessPolicy, ShareVerificationResult, ShareableSnapshotManifest
# [POS]: agent/context_management/conversation_archive_share/archive_share_types.py

"""Domain models and contracts for conversation shareable snapshots and tiered cold archiving.

[INPUT]
- None (Self-contained domain models and contracts).

[OUTPUT]
- ArchiveTier: Enumeration of session storage tiers (ACTIVE, COLD_HIBERNATED, DEEP_FROZEN).
- ShareAccessPolicy: Policy governing snapshot visibility and protection.
- SanitizedShareMessage: Cleaned message turn with stripped credentials and internal metadata.
- ShareableSnapshotManifest: Signed, immutable snapshot manifest for public or authenticated sharing.
- ColdArchiveRecord: Compressed cold session archive container with checksum and index metadata.
- ShareVerificationResult: Validation outcome verifying HMAC signature and TTL expiration.
- ConversationArchiveShareConfig: Configuration governing secrets redaction, TTL, and HMAC secret.

[POS]
Domain contract layer for sanitized sharing and tiered cold archiving in context management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class ArchiveTier(str, Enum):
    """Lifecycle storage tier for conversation sessions."""

    ACTIVE = "active"                      # Resident in memory or hot SQLite tables
    COLD_HIBERNATED = "cold_hibernated"    # Compressed byte payload offloaded from memory
    DEEP_FROZEN = "deep_frozen"            # Long-term read-only snapshot in cold block store


class ShareAccessPolicy(str, Enum):
    """Access policy governing shared conversation snapshots."""

    PUBLIC_READONLY = "public_readonly"
    AUTHENTICATED_READONLY = "authenticated_readonly"
    PASSWORD_PROTECTED = "password_protected"


@dataclass(frozen=True)
class SanitizedShareMessage:
    """A sanitized turn message safe for external read-only display."""

    role: str
    content: str
    timestamp: float
    sanitized_tool_calls: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ShareableSnapshotManifest:
    """Immutable, signed snapshot manifest for safe external sharing."""

    share_id: str
    session_id: str
    title: str
    messages: tuple[SanitizedShareMessage, ...]
    signature: str
    created_at: float
    expires_at: float | None
    redactions_count: int
    policy: ShareAccessPolicy = ShareAccessPolicy.PUBLIC_READONLY


@dataclass(frozen=True)
class ShareVerificationResult:
    """Result of signature and expiration verification on a share snapshot."""

    is_valid: bool
    is_expired: bool
    reason: str
    manifest: ShareableSnapshotManifest | None = None


@dataclass(frozen=True)
class ColdArchiveRecord:
    """Compressed cold archive container with checksum and light index excerpt."""

    session_id: str
    title: str
    total_messages: int
    total_tokens: int
    archived_at: float
    tier: ArchiveTier
    compressed_payload_bytes: bytes
    checksum: str
    summary_excerpt: str


@dataclass(frozen=True)
class ConversationArchiveShareConfig:
    """Configuration governing share secrets redaction, signing, and archiving."""

    signing_secret: str = "default-insecure-share-hmac-secret-change-in-prod"
    default_share_ttl_seconds: float = 604800.0  # 7 days
    enable_compression: bool = True
    max_snapshot_messages: int = 500
    sensitive_patterns: tuple[str, ...] = (
        r"sk-[a-zA-Z0-9]{20,}",                # OpenAI / Anthropic API keys
        r"ghp_[a-zA-Z0-9]{36}",                # GitHub personal access tokens
        r"AKIA[0-9A-Z]{16}",                   # AWS Access Key ID
        r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}", # Bearer tokens
        r"(?i)password\s*[:=]\s*['\"][^'\"]+['\"]", # Passwords
    )
