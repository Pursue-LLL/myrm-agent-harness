# [INPUT]: ArchiveTier, ColdArchiveRecord, ConversationArchiveShareConfig
# [OUTPUT]: TieredColdStorageArchiver
# [POS]: agent/context_management/conversation_archive_share/tiered_cold_storage_archiver.py

"""Tiered cold storage archiver with lossless compression and instant wakeup.

[INPUT]
- ArchiveTier, ColdArchiveRecord, ConversationArchiveShareConfig: Domain types.

[OUTPUT]
- TieredColdStorageArchiver: Manages hibernation to compressed payloads and instant lossless session wakeup.

[POS]
Cold storage compression, offline index matching, and session lifecycle restoration layer.
"""

from __future__ import annotations

import hashlib
import json
import time
import zlib
from typing import Mapping, Sequence

from .archive_share_types import (
    ArchiveTier,
    ColdArchiveRecord,
    ConversationArchiveShareConfig,
)


class TieredColdStorageArchiver:
    """Compresses idle sessions to cold storage payloads, maintains index, and wakes on demand."""

    def __init__(self, config: ConversationArchiveShareConfig | None = None) -> None:
        self._config = config or ConversationArchiveShareConfig()
        # session_id -> ColdArchiveRecord
        self._archives: dict[str, ColdArchiveRecord] = {}

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
        """Compresses full session data into an immutable byte archive and clears active residency."""
        now = timestamp if timestamp is not None else time.time()
        raw_bytes = session_payload_json.encode("utf-8")
        checksum = hashlib.sha256(raw_bytes).hexdigest()

        # Compress payload
        if self._config.enable_compression:
            compressed_bytes = zlib.compress(raw_bytes, level=6)
        else:
            compressed_bytes = raw_bytes

        record = ColdArchiveRecord(
            session_id=session_id,
            title=title,
            total_messages=total_messages,
            total_tokens=total_tokens,
            archived_at=now,
            tier=tier,
            compressed_payload_bytes=compressed_bytes,
            checksum=checksum,
            summary_excerpt=summary_excerpt,
        )

        self._archives[session_id] = record
        return record

    def wake_session(self, session_id: str) -> tuple[ColdArchiveRecord, str]:
        """Decompresses and verifies cold archive payload, returning record and restored JSON."""
        if session_id not in self._archives:
            raise KeyError(f"Session '{session_id}' not found in cold archives.")

        record = self._archives[session_id]

        # Decompress payload
        if self._config.enable_compression:
            raw_bytes = zlib.decompress(record.compressed_payload_bytes)
        else:
            raw_bytes = record.compressed_payload_bytes

        # Verify integrity
        restored_checksum = hashlib.sha256(raw_bytes).hexdigest()
        if restored_checksum != record.checksum:
            raise ValueError(
                f"Checksum mismatch for session '{session_id}': expected {record.checksum}, got {restored_checksum}"
            )

        restored_json = raw_bytes.decode("utf-8")

        # Update tier to ACTIVE
        active_record = ColdArchiveRecord(
            session_id=record.session_id,
            title=record.title,
            total_messages=record.total_messages,
            total_tokens=record.total_tokens,
            archived_at=record.archived_at,
            tier=ArchiveTier.ACTIVE,
            compressed_payload_bytes=record.compressed_payload_bytes,
            checksum=record.checksum,
            summary_excerpt=record.summary_excerpt,
        )
        self._archives[session_id] = active_record

        return active_record, restored_json

    def search_cold_archives(self, query: str) -> tuple[ColdArchiveRecord, ...]:
        """Performs lightweight keyword search over cold archive titles and excerpts without decompressing."""
        q = query.strip().lower()
        if not q:
            return tuple(self._archives.values())

        matched: list[ColdArchiveRecord] = []
        for record in self._archives.values():
            if q in record.title.lower() or q in record.summary_excerpt.lower():
                matched.append(record)

        return tuple(matched)

    def get_archive(self, session_id: str) -> ColdArchiveRecord | None:
        """Retrieves cold archive record by session ID."""
        return self._archives.get(session_id)

    def delete_archive(self, session_id: str) -> bool:
        """Removes a session archive permanently."""
        if session_id in self._archives:
            del self._archives[session_id]
            return True
        return False

    @property
    def total_archived_count(self) -> int:
        """Returns total number of sessions currently archived."""
        return len(self._archives)
