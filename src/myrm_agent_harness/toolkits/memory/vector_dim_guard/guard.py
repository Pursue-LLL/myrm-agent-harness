"""Vector index dimension guard validating dimensionality and triggering non-destructive rebuilds.

[INPUT]
- Vector collection names, expected embedding dimensions, and drop_data safety flags.

[OUTPUT]
- VectorDimGuard providing index dimension inspection and non-destructive index recreation.

[POS]
- Dimension guard module for Item 151 VectorDimGuardAndRebuildTaskSuite.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .models import DimGuardResult

logger = logging.getLogger(__name__)


@dataclass
class VectorCollectionMetadata:
    """Internal schema metadata tracking vector index configuration and document storage."""

    collection: str
    dimension: int
    documents: dict[str, dict[str, str | list[float]]] = field(default_factory=dict)


class VectorDimGuard:
    """Enforces vector index dimension alignment and prevents silent index degradation.

    Guarantees:
    1. Dimension mismatch triggers rebuild automatically.
    2. Rebuild preserves underlying document content and metadata (drop_data=False).
    3. Dimension match bypasses unnecessary reconstruction.
    """

    def __init__(self) -> None:
        self._collections: dict[str, VectorCollectionMetadata] = {}

    def register_collection(
        self,
        collection: str,
        dimension: int,
        documents: dict[str, dict[str, str | list[float]]] | None = None,
    ) -> None:
        """Register or populate an index collection metadata state."""
        self._collections[collection] = VectorCollectionMetadata(
            collection=collection,
            dimension=dimension,
            documents=documents or {},
        )

    def get_document_count(self, collection: str) -> int:
        """Return the count of stored data documents in the specified collection."""
        meta = self._collections.get(collection)
        return len(meta.documents) if meta else 0

    def inspect_dim(self, collection: str, expected_dim: int) -> DimGuardResult:
        """Inspect collection existence and dimension match without mutating state."""
        meta = self._collections.get(collection)
        if meta is None:
            return DimGuardResult(
                collection=collection,
                exists=False,
                current_dim=None,
                expected_dim=expected_dim,
                dim_match=False,
                needs_rebuild=True,
                data_intact=True,
                message=f"Collection '{collection}' does not exist; index creation required.",
            )

        match = meta.dimension == expected_dim
        return DimGuardResult(
            collection=collection,
            exists=True,
            current_dim=meta.dimension,
            expected_dim=expected_dim,
            dim_match=match,
            needs_rebuild=not match,
            data_intact=True,
            message=(
                f"Collection '{collection}' dimension matches ({expected_dim})."
                if match
                else f"Dimension mismatch: current {meta.dimension} != expected {expected_dim}; rebuild required."
            ),
        )

    def ensure_index(
        self,
        collection: str,
        expected_dim: int,
        drop_data: bool = False,
    ) -> DimGuardResult:
        """Ensure index exists with expected dimension; rebuild non-destructively on mismatch."""
        inspection = self.inspect_dim(collection, expected_dim)
        if not inspection.needs_rebuild:
            return inspection

        # Handle reconstruction
        existing_meta = self._collections.get(collection)
        preserved_docs: dict[str, dict[str, str | list[float]]] = {}
        if existing_meta is not None and not drop_data:
            # Preserve raw document content and metadata (never drop data during dim rebuild)
            preserved_docs = existing_meta.documents

        self._collections[collection] = VectorCollectionMetadata(
            collection=collection,
            dimension=expected_dim,
            documents=preserved_docs,
        )

        logger.info(
            "Rebuilt vector index for '%s' to dimension %d (preserved %d docs, drop_data=%s)",
            collection,
            expected_dim,
            len(preserved_docs),
            drop_data,
        )

        return DimGuardResult(
            collection=collection,
            exists=True,
            current_dim=expected_dim,
            expected_dim=expected_dim,
            dim_match=True,
            needs_rebuild=False,
            data_intact=not drop_data,
            message=f"Successfully rebuilt vector index for '{collection}' to dimension {expected_dim}.",
        )
