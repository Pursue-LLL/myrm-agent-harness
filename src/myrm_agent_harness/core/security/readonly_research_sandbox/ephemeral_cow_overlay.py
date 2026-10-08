"""
[POS] src/myrm_agent_harness/core/security/readonly_research_sandbox/ephemeral_cow_overlay.py
[INPUT] hashlib, threading, time, uuid, typing, .types (EphemeralCowFileRecord, WorkspaceSnapshot)
[OUTPUT] EphemeralCowOverlay

Provides immutable workspace baselines and in-memory Copy-on-Write (CoW) overlays
for transient research calculations, guaranteeing 100% zero-pollution workspace purity.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid

from .types import EphemeralCowFileRecord, WorkspaceSnapshot


class EphemeralCowOverlay:
    """Manages immutable snapshots and transient in-memory file overlays."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots: dict[str, WorkspaceSnapshot] = {}  # session_id -> snapshot
        self._overlays: dict[str, dict[str, EphemeralCowFileRecord]] = {}  # session_id -> path -> record

    @staticmethod
    def _compute_hash(data: str | bytes) -> str:
        b = data.encode("utf-8") if isinstance(data, str) else data
        return hashlib.sha256(b).hexdigest()

    def take_snapshot(
        self, session_id: str, baseline_files: dict[str, str | bytes]
    ) -> WorkspaceSnapshot:
        """Capture immutable cryptographic baseline snapshot of protected workspace."""
        sid = f"snap-{uuid.uuid4().hex[:12]}"
        now = time.time()

        manifest: dict[str, str] = {}
        for path, content in sorted(baseline_files.items()):
            manifest[path] = self._compute_hash(content)

        combined_manifest = ";".join(f"{k}:{v}" for k, v in manifest.items())
        root_digest = self._compute_hash(combined_manifest)

        snapshot = WorkspaceSnapshot(
            snapshot_id=sid,
            session_id=session_id,
            baseline_timestamp=now,
            file_manifest_hashes=manifest,
            root_digest=root_digest,
        )

        with self._lock:
            self._snapshots[session_id] = snapshot
            if session_id not in self._overlays:
                self._overlays[session_id] = {}

        return snapshot

    def get_snapshot(self, session_id: str) -> WorkspaceSnapshot | None:
        """Retrieve baseline snapshot for a session."""
        with self._lock:
            return self._snapshots.get(session_id)

    def write_ephemeral_file(
        self, session_id: str, virtual_path: str, content: str | bytes
    ) -> EphemeralCowFileRecord:
        """Write intermediate research output strictly into transient memory CoW overlay."""
        data_bytes = content.encode("utf-8") if isinstance(content, str) else content
        sha = hashlib.sha256(data_bytes).hexdigest()
        now = time.time()

        rec = EphemeralCowFileRecord(
            virtual_path=virtual_path,
            file_bytes=data_bytes,
            sha256_hash=sha,
            written_at=now,
        )

        with self._lock:
            if session_id not in self._overlays:
                self._overlays[session_id] = {}
            self._overlays[session_id][virtual_path] = rec

        return rec

    def read_ephemeral_file(self, session_id: str, virtual_path: str) -> bytes | None:
        """Read intermediate file from in-memory CoW layer."""
        with self._lock:
            session_overlay = self._overlays.get(session_id)
            if session_overlay is None:
                return None
            rec = session_overlay.get(virtual_path)
            return rec.file_bytes if rec else None

    def list_ephemeral_files(self, session_id: str) -> list[EphemeralCowFileRecord]:
        """List all transient files created in session's CoW overlay."""
        with self._lock:
            session_overlay = self._overlays.get(session_id)
            if not session_overlay:
                return []
            return list(session_overlay.values())

    def purge_overlay(self, session_id: str) -> int:
        """Instantly destroy in-memory CoW overlay upon research task completion."""
        with self._lock:
            session_overlay = self._overlays.pop(session_id, {})
            return len(session_overlay)

    def verify_workspace_purity(
        self, session_id: str, current_files: dict[str, str | bytes]
    ) -> tuple[bool, str]:
        """Verify that current workspace matches pre-lease snapshot without tampering or leftover pollution.

        Returns:
            Tuple of (is_pure, explanation)
        """
        with self._lock:
            snap = self._snapshots.get(session_id)

        if snap is None:
            return True, "No baseline snapshot was recorded for this session."

        current_manifest: dict[str, str] = {}
        for path, content in sorted(current_files.items()):
            current_manifest[path] = self._compute_hash(content)

        combined = ";".join(f"{k}:{v}" for k, v in current_manifest.items())
        current_root = self._compute_hash(combined)

        if current_root == snap.root_digest:
            return True, "Workspace is 100% pure and bit-identical to immutable baseline snapshot."

        # Detect differences
        added = set(current_manifest.keys()) - set(snap.file_manifest_hashes.keys())
        deleted = set(snap.file_manifest_hashes.keys()) - set(current_manifest.keys())
        modified = [
            k for k in current_manifest if k in snap.file_manifest_hashes and current_manifest[k] != snap.file_manifest_hashes[k]
        ]

        details = f"Pollution detected: {len(added)} added, {len(deleted)} deleted, {len(modified)} modified."
        return False, details
