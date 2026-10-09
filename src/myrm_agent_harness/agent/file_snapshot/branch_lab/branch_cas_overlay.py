"""Content-addressed storage and copy-on-write sparse overlay for branch lab.

[INPUT]
Raw file contents (bytes), file paths, mutation records from branch operations.

[OUTPUT]
BranchCasOverlay managing deduplicated blob storage and per-branch file mutations.

[POS]
CAS overlay engine inside file_snapshot/branch_lab.
"""

from __future__ import annotations

import hashlib
import logging

from .branch_types import BranchMutation, MutationType

logger = logging.getLogger(__name__)


class BranchCasOverlay:
    """Content-addressed deduplicated storage with copy-on-write overlays."""

    def __init__(self) -> None:
        self._blob_store: dict[str, bytes] = {}
        self._blob_ref_counts: dict[str, int] = {}
        self._branch_overlays: dict[str, dict[str, BranchMutation]] = {}

    def record_write(
        self,
        branch_id: str,
        file_path: str,
        content: bytes,
        old_size: int | None = None,
    ) -> BranchMutation:
        """Record an added or modified file in the branch overlay.

        Deduplicates content in the central content-addressed blob store.
        """
        content_hash = hashlib.sha256(content).hexdigest()
        byte_size = len(content)

        if content_hash not in self._blob_store:
            self._blob_store[content_hash] = content
            self._blob_ref_counts[content_hash] = 1
        else:
            self._blob_ref_counts[content_hash] = self._blob_ref_counts.get(content_hash, 0) + 1

        if branch_id not in self._branch_overlays:
            self._branch_overlays[branch_id] = {}

        existing = self._branch_overlays[branch_id].get(file_path)
        mutation_type = (
            MutationType.MODIFIED
            if (existing is not None or (old_size is not None and old_size > 0))
            else MutationType.ADDED
        )

        mutation = BranchMutation(
            file_path=file_path,
            mutation_type=mutation_type,
            content_hash=content_hash,
            byte_size=byte_size,
            old_size=old_size,
        )
        self._branch_overlays[branch_id][file_path] = mutation
        return mutation

    def record_delete(
        self,
        branch_id: str,
        file_path: str,
        old_size: int | None = None,
    ) -> BranchMutation:
        """Record a file deletion within the branch overlay."""
        if branch_id not in self._branch_overlays:
            self._branch_overlays[branch_id] = {}

        mutation = BranchMutation(
            file_path=file_path,
            mutation_type=MutationType.DELETED,
            content_hash="",
            byte_size=0,
            old_size=old_size,
        )
        self._branch_overlays[branch_id][file_path] = mutation
        return mutation

    def get_file_content(self, branch_id: str, file_path: str) -> bytes | None:
        """Retrieve latest mutated content for a file on this branch."""
        branch_files = self._branch_overlays.get(branch_id)
        if not branch_files:
            return None

        mutation = branch_files.get(file_path)
        if mutation is None or mutation.mutation_type == MutationType.DELETED:
            return None

        return self._blob_store.get(mutation.content_hash)

    def get_branch_mutations(self, branch_id: str) -> list[BranchMutation]:
        """Return all mutations staged for a specific branch."""
        branch_files = self._branch_overlays.get(branch_id, {})
        return list(branch_files.values())

    def calculate_branch_delta_bytes(self, branch_id: str) -> int:
        """Compute the sum of added and modified bytes staged in this branch."""
        mutations = self.get_branch_mutations(branch_id)
        return sum(m.byte_size for m in mutations if m.mutation_type != MutationType.DELETED)

    def clear_branch_overlay(self, branch_id: str) -> int:
        """Clear all overlay mutations for this branch and prune unreferenced blobs.

        Returns:
            The number of reclaimed bytes freed from deduplicated storage.
        """
        branch_files = self._branch_overlays.pop(branch_id, {})
        if not branch_files:
            return 0

        reclaimed_bytes = 0
        for mutation in branch_files.values():
            if not mutation.content_hash:
                continue

            current_refs = self._blob_ref_counts.get(mutation.content_hash, 0)
            if current_refs <= 1:
                self._blob_ref_counts.pop(mutation.content_hash, None)
                removed_blob = self._blob_store.pop(mutation.content_hash, None)
                if removed_blob is not None:
                    reclaimed_bytes += len(removed_blob)
            else:
                self._blob_ref_counts[mutation.content_hash] = current_refs - 1

        return reclaimed_bytes
