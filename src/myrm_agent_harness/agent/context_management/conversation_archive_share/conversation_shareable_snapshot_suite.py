"""Unified facade suite for conversation shareable snapshots and tiered cold archiving.

[INPUT]
- ArchiveTier, ColdArchiveRecord, ConversationArchiveShareConfig, SanitizedShareMessage: Domain models.
- SanitizedSnapshotExporter: Credentials redaction and cryptographic signing engine.
- SignedShareGateway: Read-only access verification and TTL lifecycle gateway.
- TieredColdStorageArchiver: Lossless compression and instant session wakeup archiver.

[OUTPUT]
- ConversationShareableSnapshotAndTieredColdArchiveSuite: Cohesive facade coordinating sanitized public/authenticated
  sharing, tamper-evident verification, cold session hibernation, and instant wakeup.

[POS]
Top-level entry point for conversation sharing and cold storage governance in context management.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .archive_share_types import (
    ArchiveTier,
    ColdArchiveRecord,
    ConversationArchiveShareConfig,
    SanitizedShareMessage,
    ShareAccessPolicy,
    ShareVerificationResult,
    ShareableSnapshotManifest,
)
from .sanitized_snapshot_exporter import SanitizedSnapshotExporter
from .signed_share_gateway import SignedShareGateway
from .tiered_cold_storage_archiver import TieredColdStorageArchiver


class ConversationShareableSnapshotAndTieredColdArchiveSuite:
    """Industrial facade coordinating sanitized sharing, HMAC verification, cold hibernation, and wakeup."""

    def __init__(
        self,
        config: ConversationArchiveShareConfig | None = None,
        exporter: SanitizedSnapshotExporter | None = None,
        gateway: SignedShareGateway | None = None,
        archiver: TieredColdStorageArchiver | None = None,
    ) -> None:
        self._config = config or ConversationArchiveShareConfig()
        self._exporter = exporter or SanitizedSnapshotExporter(self._config)
        self._gateway = gateway or SignedShareGateway(self._exporter)
        self._archiver = archiver or TieredColdStorageArchiver(self._config)

    @property
    def config(self) -> ConversationArchiveShareConfig:
        """Returns the active configuration."""
        return self._config

    @property
    def exporter(self) -> SanitizedSnapshotExporter:
        """Returns the internal snapshot exporter."""
        return self._exporter

    @property
    def gateway(self) -> SignedShareGateway:
        """Returns the internal share verification gateway."""
        return self._gateway

    @property
    def archiver(self) -> TieredColdStorageArchiver:
        """Returns the internal tiered cold storage archiver."""
        return self._archiver

    @property
    def total_shares_count(self) -> int:
        """Returns the total number of registered shareable snapshots."""
        return self._gateway.total_shares_count

    @property
    def total_archived_count(self) -> int:
        """Returns the total number of cold archived sessions."""
        return self._archiver.total_archived_count

    def create_shareable_snapshot(
        self,
        session_id: str,
        title: str,
        raw_messages: Sequence[Mapping[str, str | float | Sequence[str]]],
        ttl_seconds: float | None = None,
        policy: ShareAccessPolicy = ShareAccessPolicy.PUBLIC_READONLY,
        timestamp: float | None = None,
        share_id: str | None = None,
    ) -> ShareableSnapshotManifest:
        """Sanitizes sensitive credentials, generates HMAC signature, and registers share in gateway."""
        manifest = self._exporter.export_snapshot(
            session_id=session_id,
            title=title,
            raw_messages=raw_messages,
            ttl_seconds=ttl_seconds,
            policy=policy,
            timestamp=timestamp,
            share_id=share_id,
        )
        self._gateway.register_snapshot(manifest)
        return manifest

    def verify_and_access_share(
        self,
        share_id: str,
        timestamp: float | None = None,
    ) -> ShareVerificationResult:
        """Verifies HMAC signature and expiration before yielding read-only view."""
        return self._gateway.verify_and_access(share_id=share_id, timestamp=timestamp)

    def revoke_share(self, share_id: str) -> bool:
        """Revokes an active share snapshot immediately."""
        return self._gateway.revoke_share(share_id)

    def list_shares_for_session(self, session_id: str) -> tuple[ShareableSnapshotManifest, ...]:
        """Lists all snapshots associated with a specific session."""
        return self._gateway.list_shares_for_session(session_id)

    def hibernate_session(
        self,
        session_id: str,
        title: str,
        session_payload_json: str,
        total_messages: int,
        total_tokens: int,
        summary_excerpt: str = "",
        tier: ArchiveTier = ArchiveTier.COLD_HIBERNATED,
        timestamp: float | None = None,
    ) -> ColdArchiveRecord:
        """Compresses full session data into an immutable byte archive and offloads from active memory."""
        return self._archiver.hibernate_session(
            session_id=session_id,
            title=title,
            session_payload_json=session_payload_json,
            total_messages=total_messages,
            total_tokens=total_tokens,
            summary_excerpt=summary_excerpt,
            tier=tier,
            timestamp=timestamp,
        )

    def wake_session(self, session_id: str) -> tuple[ColdArchiveRecord, str]:
        """Decompresses and verifies cold archive payload, returning record and restored JSON."""
        return self._archiver.wake_session(session_id)

    def search_cold_archives(self, query: str) -> tuple[ColdArchiveRecord, ...]:
        """Lightweight keyword search over cold archive titles and excerpts without decompressing."""
        return self._archiver.search_cold_archives(query)

    def get_archive(self, session_id: str) -> ColdArchiveRecord | None:
        """Retrieves cold archive record by session ID."""
        return self._archiver.get_archive(session_id)

    def delete_archive(self, session_id: str) -> bool:
        """Removes a session archive permanently."""
        return self._archiver.delete_archive(session_id)
