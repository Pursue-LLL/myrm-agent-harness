"""Signed ephemeral share gateway verifying HMAC signatures and TTL expirations.

[INPUT]
- SanitizedSnapshotExporter, ShareVerificationResult, ShareableSnapshotManifest: Domain models.

[OUTPUT]
- SignedShareGateway: Gateway validating shareable links, verifying tamper signatures, and managing TTLs.

[POS]
Access verification and readonly projection layer for shareable conversation snapshots.
"""

from __future__ import annotations

import hmac
import time
from typing import Mapping, Sequence

from .archive_share_types import ShareVerificationResult, ShareableSnapshotManifest
from .sanitized_snapshot_exporter import SanitizedSnapshotExporter


class SignedShareGateway:
    """Gateway managing read-only snapshot storage, signature verification, and TTL lifecycle."""

    def __init__(self, exporter: SanitizedSnapshotExporter) -> None:
        self._exporter = exporter
        # share_id -> ShareableSnapshotManifest
        self._snapshots: dict[str, ShareableSnapshotManifest] = {}

    def register_snapshot(self, manifest: ShareableSnapshotManifest) -> None:
        """Stores a signed manifest in the gateway repository."""
        self._snapshots[manifest.share_id] = manifest

    def verify_and_access(
        self,
        share_id: str,
        timestamp: float | None = None,
    ) -> ShareVerificationResult:
        """Verifies signature integrity and expiration status before granting read-only access."""
        now = timestamp if timestamp is not None else time.time()

        if share_id not in self._snapshots:
            return ShareVerificationResult(
                is_valid=False,
                is_expired=False,
                reason=f"Share snapshot '{share_id}' not found.",
                manifest=None,
            )

        manifest = self._snapshots[share_id]

        # 1. Check expiration
        if manifest.expires_at is not None and now > manifest.expires_at:
            return ShareVerificationResult(
                is_valid=False,
                is_expired=True,
                reason=f"Share snapshot '{share_id}' expired at {manifest.expires_at:.1f}.",
                manifest=manifest,
            )

        # 2. Verify HMAC signature to prevent tampering
        expected_sig = self._exporter.compute_signature(
            share_id=manifest.share_id,
            session_id=manifest.session_id,
            title=manifest.title,
            messages=manifest.messages,
            expires_at=manifest.expires_at,
        )

        if not hmac.compare_digest(manifest.signature, expected_sig):
            return ShareVerificationResult(
                is_valid=False,
                is_expired=False,
                reason="Signature mismatch: manifest has been modified or corrupted.",
                manifest=None,
            )

        return ShareVerificationResult(
            is_valid=True,
            is_expired=False,
            reason="Snapshot verified successfully.",
            manifest=manifest,
        )

    def revoke_share(self, share_id: str) -> bool:
        """Revokes an active share snapshot immediately."""
        if share_id in self._snapshots:
            del self._snapshots[share_id]
            return True
        return False

    def list_shares_for_session(self, session_id: str) -> tuple[ShareableSnapshotManifest, ...]:
        """Lists all snapshots associated with a specific session."""
        return tuple(
            m for m in self._snapshots.values()
            if m.session_id == session_id
        )

    @property
    def total_shares_count(self) -> int:
        """Returns the total number of managed share snapshots."""
        return len(self._snapshots)
