"""Deterministic garbage collection sweeper for unreferenced storage blobs."""

import os
from pathlib import Path
from time import perf_counter

from myrm_agent_harness.toolkits.memory.document_attachment.models import (
    ReclaimAuditReport,
    StorageBlobMetadata,
)
from myrm_agent_harness.toolkits.memory.document_attachment.ownership_engine import (
    DocumentAttachmentOwnershipEngine,
)


class DeterministicReclaimSweeper:
    """Scans and deterministic reclaims blobs with non-positive reference counts."""

    def __init__(self, ownership_engine: DocumentAttachmentOwnershipEngine) -> None:
        self._engine: DocumentAttachmentOwnershipEngine = ownership_engine

    def sweep(self) -> ReclaimAuditReport:
        """Executes a garbage collection sweep over all tracked storage blobs.

        Reclaims any blob where ref_count <= 0, unlinking the physical file
        if present, and removing the blob entry from the engine.
        """
        start_time: float = perf_counter()
        all_blobs: list[StorageBlobMetadata] = self._engine.get_all_storage_blobs()

        reclaimed_keys: list[str] = []
        freed_bytes: int = 0
        retained_count: int = 0

        for blob in all_blobs:
            if blob.ref_count <= 0:
                # Perform physical unlink if file exists on disk
                if blob.physical_path is not None:
                    try:
                        path_obj: Path = Path(blob.physical_path)
                        if path_obj.exists() and path_obj.is_file():
                            os.unlink(path_obj)
                    except OSError:
                        # Continue reclaiming memory index even if OS file was already removed
                        pass

                freed_bytes += blob.byte_size
                reclaimed_keys.append(blob.storage_key)
                self._engine.internal_remove_storage_blob(blob.storage_key)
            else:
                retained_count += 1

        elapsed_ms: float = (perf_counter() - start_time) * 1000.0

        return ReclaimAuditReport(
            scanned_blobs=len(all_blobs),
            reclaimed_blobs=len(reclaimed_keys),
            freed_bytes=freed_bytes,
            retained_blobs=retained_count,
            reclaimed_storage_keys=tuple(reclaimed_keys),
            elapsed_ms=round(elapsed_ms, 3),
        )
