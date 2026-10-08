# [INPUT]: None
# [OUTPUT]: ArchiveTier, ColdArchiveRecord, ConversationArchiveShareConfig, ConversationShareableSnapshotAndTieredColdArchiveSuite, SanitizedShareMessage, SanitizedSnapshotExporter, ShareAccessPolicy, ShareVerificationResult, ShareableSnapshotManifest, SignedShareGateway, TieredColdStorageArchiver
# [POS]: agent/context_management/conversation_archive_share/__init__.py

"""Conversation shareable snapshot and tiered cold archive package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- ArchiveTier: Enumeration of session storage tiers (ACTIVE, COLD_HIBERNATED, DEEP_FROZEN).
- ColdArchiveRecord: Compressed cold session archive container.
- ConversationArchiveShareConfig: Configuration governing secrets redaction, TTL, and signing.
- ConversationShareableSnapshotAndTieredColdArchiveSuite: Unified facade coordinating sharing, verification,
  hibernation, and session wakeup.
- SanitizedShareMessage: Cleaned message turn with stripped credentials.
- SanitizedSnapshotExporter: Credentials redaction and cryptographic signing engine.
- ShareAccessPolicy: Access policy for snapshots.
- ShareVerificationResult: Validation outcome verifying HMAC signature and TTL.
- ShareableSnapshotManifest: Signed, immutable snapshot manifest.
- SignedShareGateway: Read-only access verification and TTL lifecycle gateway.
- TieredColdStorageArchiver: Lossless compression and instant session wakeup archiver.

[POS]
Package entry point for conversation sharing and cold storage in context management.
"""

from __future__ import annotations

from .archive_share_types import (
    ArchiveTier,
    ColdArchiveRecord,
    ConversationArchiveShareConfig,
    SanitizedShareMessage,
    ShareAccessPolicy,
    ShareVerificationResult,
    ShareableSnapshotManifest,
)
from .conversation_shareable_snapshot_suite import (
    ConversationShareableSnapshotAndTieredColdArchiveSuite,
)
from .sanitized_snapshot_exporter import SanitizedSnapshotExporter
from .signed_share_gateway import SignedShareGateway
from .tiered_cold_storage_archiver import TieredColdStorageArchiver

__all__ = [
    "ArchiveTier",
    "ColdArchiveRecord",
    "ConversationArchiveShareConfig",
    "ConversationShareableSnapshotAndTieredColdArchiveSuite",
    "SanitizedShareMessage",
    "SanitizedSnapshotExporter",
    "ShareAccessPolicy",
    "ShareVerificationResult",
    "ShareableSnapshotManifest",
    "SignedShareGateway",
    "TieredColdStorageArchiver",
]
