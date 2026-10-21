"""Spill-to-volume hydrator pipeline for dehydrating large tool outputs.

Prevents huge HTML documents, large SQL results, and deep CoT reasoning blocks
from bloating process heap memory by spilling compressed payloads to disk storage.

[INPUT]
- __future__
- gzip
- tempfile
- time
- uuid
- pathlib

[OUTPUT]
- SpillToVolumeHydrator

[POS]
Spill-to-volume hydrator pipeline for dehydrating large tool outputs.
"""

from __future__ import annotations

import gzip
import tempfile
import time
import uuid
from pathlib import Path

from .memory_sentinel_types import SpillHandle


class SpillToVolumeHydrator:
    """Manages dehydration of large string/byte payloads to disk and on-demand hydration."""

    def __init__(
        self,
        storage_dir: Path | str,
        threshold_bytes: int = 64 * 1024,  # 64 KB threshold
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.threshold_bytes = threshold_bytes

    def dehydrate_if_large(
        self,
        content: str,
        prefix_hint: str = "spill",
    ) -> tuple[bool, str | SpillHandle]:
        """Dehydrate content to disk if its encoded size exceeds threshold_bytes.

        Returns (True, SpillHandle) if dehydrated, or (False, content) if kept in-memory.
        """
        raw_bytes = content.encode("utf-8")
        raw_size = len(raw_bytes)

        if raw_size <= self.threshold_bytes:
            return False, content

        spill_id = f"{prefix_hint}_{uuid.uuid4().hex[:8]}"
        compressed_data = gzip.compress(raw_bytes)
        compressed_size = len(compressed_data)

        # Retain top 200 characters in memory as an immutable preview
        preview = content[:200]
        file_path = self.storage_dir / f"{spill_id}.gz"

        with tempfile.NamedTemporaryFile("wb", dir=self.storage_dir, delete=False) as tmp:
            tmp.write(compressed_data)
            tmp_path = Path(tmp.name)

        tmp_path.replace(file_path)

        handle = SpillHandle(
            spill_id=spill_id,
            disk_path=file_path,
            raw_size_bytes=raw_size,
            compressed_size_bytes=compressed_size,
            preview_snippet=preview,
            created_at=time.time(),
        )
        return True, handle

    def hydrate(self, handle: SpillHandle, max_chars: int | None = None) -> str:
        """Streamingly decompress and hydrate the payload on-demand.

        Falls back gracefully to the preview snippet if the spilled file is lost.
        """
        if not handle.disk_path.exists():
            return (
                f"[DEHYDRATED_CONTENT_UNAVAILABLE: {handle.spill_id} (original size: {handle.raw_size_bytes}B). "
                f"Preview: '{handle.preview_snippet}...']"
            )

        try:
            with gzip.open(handle.disk_path, "rt", encoding="utf-8") as f:
                if max_chars is not None:
                    return f.read(max_chars)
                return f.read()
        except Exception:
            return (
                f"[DEHYDRATED_CONTENT_CORRUPTED: {handle.spill_id}. "
                f"Preview: '{handle.preview_snippet}...']"
            )

    def delete_spill(self, handle: SpillHandle) -> bool:
        """Remove the spilled file from disk when lifecycle completes."""
        try:
            if handle.disk_path.exists():
                handle.disk_path.unlink()
                return True
        except OSError:
            pass
        return False
