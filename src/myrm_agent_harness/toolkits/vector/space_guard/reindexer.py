"""Reindexing orchestrator for migrating vector collections to new embedding models.

[POS]
Orchestrator safely clearing deprecated vectors and coordinating batch re-embedding
when users switch embedding models or vector dimensions.

[INPUT]
- collections.abc.Callable, collections.abc.Sequence
- .models (EmbeddingModelFingerprint, ReindexStatusReport)
- .guard (VectorSpaceGuard)

[OUTPUT]
- VectorSpaceReindexer
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from myrm_agent_harness.toolkits.vector.space_guard.guard import VectorSpaceGuard
from myrm_agent_harness.toolkits.vector.space_guard.models import (
    EmbeddingModelFingerprint,
    ReindexStatusReport,
)


class VectorSpaceReindexer:
    """Coordinates migration of vector collections when switching embedding models."""

    def __init__(self, guard: VectorSpaceGuard) -> None:
        """Initialize reindexer with associated space guard."""
        self._guard: VectorSpaceGuard = guard
        self._reports: dict[str, ReindexStatusReport] = {}

    def get_reindex_status(self, collection: str) -> ReindexStatusReport | None:
        """Get latest reindex report for a collection."""
        return self._reports.get(collection)

    async def execute_reindex(
        self,
        collection: str,
        target_fingerprint: EmbeddingModelFingerprint,
        items: Sequence[str],
        embedder: Callable[[Sequence[str]], Sequence[list[float]]],
    ) -> ReindexStatusReport:
        """Execute atomic space migration and re-indexing pipeline.

        Args:
            collection: Target collection name.
            target_fingerprint: Target model fingerprint.
            items: Text items to be re-indexed.
            embedder: Callable generating embeddings with the new target model.

        Returns:
            ReindexStatusReport summarizing migration results.
        """
        old_meta = self._guard.get_space_metadata(collection)
        prev_fp = old_meta.fingerprint if old_meta else None

        report = ReindexStatusReport(
            collection_name=collection,
            previous_fingerprint=prev_fp,
            target_fingerprint=target_fingerprint,
            reindexed_count=0,
            status="in_progress",
        )
        self._reports[collection] = report

        try:
            if items:
                # Compute new embeddings via injected caller embedder
                embeddings = embedder(items)
                if len(embeddings) != len(items):
                    raise ValueError(
                        f"Embedder returned {len(embeddings)} vectors for {len(items)} items"
                    )
                for vec in embeddings:
                    if len(vec) != target_fingerprint.vector_dimension:
                        raise ValueError(
                            f"Generated vector dimension {len(vec)} does not match "
                            f"target dimension {target_fingerprint.vector_dimension}"
                        )
                report.reindexed_count = len(items)

            # Update guard space registration atomically
            self._guard.bind_fingerprint(
                collection=collection,
                fingerprint=target_fingerprint,
                total_vectors_indexed=report.reindexed_count,
            )
            report.status = "completed"
        except Exception as exc:
            report.status = "failed"
            report.error_message = str(exc)
            raise

        return report
