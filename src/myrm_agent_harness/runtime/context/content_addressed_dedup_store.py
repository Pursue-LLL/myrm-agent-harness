"""Content-addressed chunk storage and session turn deduplication store.

Provides SHA-256 hash-indexed archival for large output chunks and tracks
verbatim content repetition across conversational turns.

[INPUT]
- runtime.context.content_addressed_dedup_types::ArchivedChunkMetadata, ContentRefAnchor, DedupContentType
  (POS: Strongly typed data contracts for Content-Addressed Session Dedup and CCR Context Archival.)

[OUTPUT]
- ContentAddressedDedupStore: In-memory content-addressed storage and cross-turn content tracker.

[POS]
Content-addressed chunk storage and session turn deduplication store.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict

from myrm_agent_harness.runtime.context.content_addressed_dedup_types import (
    ArchivedChunkMetadata,
    ContentRefAnchor,
    DedupContentType,
)


class ContentAddressedDedupStore:
    """In-memory content-addressed storage and cross-turn content tracker."""

    def __init__(self, max_cached_chunks: int = 1000) -> None:
        self.max_cached_chunks = max_cached_chunks
        # Mapping: content_hash -> verbatim content (LRU order)
        self._content_by_hash: OrderedDict[str, str] = OrderedDict()
        # Mapping: marker_id -> content_hash
        self._hash_by_marker_id: dict[str, str] = {}
        # Mapping: content_hash -> metadata
        self._meta_by_hash: dict[str, ArchivedChunkMetadata] = {}
        # Mapping: source_hint -> (content_hash, first_seen_turn)
        self._session_history: dict[str, tuple[str, int]] = {}

    def compute_hash(self, content: str) -> str:
        """Compute standard SHA-256 hexadecimal digest for string."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def store_content(
        self,
        content: str,
        content_type: DedupContentType,
        source_hint: str = "unknown_source",
        preview_chars: int = 120,
    ) -> ArchivedChunkMetadata:
        """Store content addressed by its SHA-256 digest and return chunk metadata."""
        digest = self.compute_hash(content)
        marker_id = f"chunk_{digest[:12]}"

        if digest in self._meta_by_hash:
            # Re-touch in LRU cache
            self._content_by_hash.move_to_end(digest)
            return self._meta_by_hash[digest]

        # Enforce cache capacity
        if len(self._content_by_hash) >= self.max_cached_chunks:
            oldest_hash, _ = self._content_by_hash.popitem(last=False)
            old_meta = self._meta_by_hash.pop(oldest_hash, None)
            if old_meta:
                self._hash_by_marker_id.pop(old_meta.marker_id, None)

        clean_preview = " ".join(content.strip().split()[:20])
        if len(clean_preview) > preview_chars:
            clean_preview = clean_preview[:preview_chars] + "..."

        line_count = len(content.splitlines())
        byte_size = len(content.encode("utf-8"))
        archived_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        meta = ArchivedChunkMetadata(
            marker_id=marker_id,
            content_hash=digest,
            content_type=content_type,
            source_hint=source_hint,
            byte_size=byte_size,
            line_count=line_count,
            preview_summary=clean_preview,
            archived_at_utc=archived_at_utc,
        )

        self._content_by_hash[digest] = content
        self._hash_by_marker_id[marker_id] = digest
        self._meta_by_hash[digest] = meta
        return meta

    def retrieve_content(self, marker_id_or_hash: str) -> str | None:
        """Retrieve stored content by marker_id or sha256 hash."""
        key = marker_id_or_hash.strip()
        digest = self._hash_by_marker_id.get(key, key)
        content = self._content_by_hash.get(digest)
        if content is not None:
            self._content_by_hash.move_to_end(digest)
        return content

    def get_metadata(self, marker_id_or_hash: str) -> ArchivedChunkMetadata | None:
        """Look up metadata descriptor by marker_id or hash."""
        key = marker_id_or_hash.strip()
        digest = self._hash_by_marker_id.get(key, key)
        return self._meta_by_hash.get(digest)

    def track_session_turn(
        self,
        turn_index: int,
        source_hint: str,
        content: str,
    ) -> tuple[bool, ContentRefAnchor | None]:
        """Track content by source hint; detect verbatim unchanged repetition across turns.

        Returns (is_repeated, anchor_if_repeated).
        """
        digest = self.compute_hash(content)
        prior = self._session_history.get(source_hint)

        if prior is not None:
            prior_hash, first_turn = prior
            if prior_hash == digest and first_turn < turn_index:
                anchor = ContentRefAnchor(
                    content_hash=digest,
                    source_hint=source_hint,
                    line_count=len(content.splitlines()),
                    first_seen_turn=first_turn,
                )
                return True, anchor

        # Update or initialize record
        first_turn = prior[1] if (prior is not None and prior[0] == digest) else turn_index
        self._session_history[source_hint] = (digest, first_turn)
        return False, None
