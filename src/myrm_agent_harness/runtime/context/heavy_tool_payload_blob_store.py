"""Heavy tool payload blob store and detachment manager.

Isolates oversized tool outputs (Shell logs, huge JSON payloads, file diffs)
into dedicated lazy blob references, eliminating serialization bottlenecks.

[INPUT]
- runtime.context.bounded_hydration_types::HeavyToolBlobReference (POS: Types and data models for bounded
  initial page loading and upward cursor hydration.)

[OUTPUT]
- HeavyToolPayloadBlobStore: Stores detached heavy tool outputs and serves on-demand lazy hydration.

[POS]
Heavy tool payload blob store and detachment manager.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.bounded_hydration_types import (
    HeavyToolBlobReference,
)


class HeavyToolPayloadBlobStore:
    """Stores detached heavy tool outputs and serves on-demand lazy hydration."""

    def __init__(self, spill_threshold_bytes: int = 2048) -> None:
        self._spill_threshold_bytes = max(spill_threshold_bytes, 256)
        self._blobs: dict[str, str] = {}

    @property
    def total_stored_blobs(self) -> int:
        """Total number of detached payloads currently held in store."""
        return len(self._blobs)

    def detect_and_detach_payload(
        self,
        content: str,
        preview_length: int = 120,
        content_type: str = "text/plain",
    ) -> tuple[str, HeavyToolBlobReference | None]:
        """Detect if content exceeds spill threshold; if so, detach and return blob ref.

        Returns a tuple of (stub_or_original_content, blob_reference_or_none).
        """
        encoded_len = len(content.encode("utf-8"))
        if encoded_len <= self._spill_threshold_bytes:
            return content, None

        blob_id = f"blob_{uuid.uuid4().hex[:12]}"
        self._blobs[blob_id] = content

        preview = content[:preview_length].strip()
        preview_text = f"{preview} ... [DETACHED_BLOB:{blob_id}:{encoded_len}B]"

        ref = HeavyToolBlobReference(
            blob_id=blob_id,
            original_size_bytes=encoded_len,
            content_preview=preview_text,
            content_type=content_type,
            timestamp=time.time(),
        )
        return preview_text, ref

    def fetch_blob_payload(self, blob_id: str) -> str | None:
        """Fetch the full original content payload by blob ID on demand."""
        return self._blobs.get(blob_id)

    def has_blob(self, blob_id: str) -> bool:
        """Check whether the given blob exists in store."""
        return blob_id in self._blobs

    def purge_blobs(self, blob_ids: Sequence[str]) -> int:
        """Purge specified blobs from memory and return the count of removed items."""
        removed_count = 0
        for b_id in blob_ids:
            if self._blobs.pop(b_id, None) is not None:
                removed_count += 1
        return removed_count

    def clear(self) -> None:
        """Clear all detached payloads from store."""
        self._blobs.clear()
