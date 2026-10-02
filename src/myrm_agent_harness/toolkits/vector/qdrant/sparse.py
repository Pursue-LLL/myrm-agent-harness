"""Qdrant Sparse-Vector Operations.

[INPUT]
myrm_agent_harness.toolkits.vector.base (POS: SparsePoint model)
myrm_agent_harness.toolkits.vector.qdrant.filters (POS: Qdrant filter builder)
qdrant_client (POS: Qdrant SDK, optional dependency)

[OUTPUT]
QdrantSparseMixin: ensure/upsert/search sparse-vector methods for QdrantVectorStore

[POS]
Sparse-vector layer for the Qdrant backend. Hosts a ``bm25`` named sparse
vector per collection so hash-indexed term-frequency retrieval (server-side
IDF weighting) works as a persistent, incrementally-maintained BM25 channel
without rebuilding a client-side corpus index per query. Mixin is hosted by
QdrantVectorStore, which supplies ``_client`` / ``_with_retry`` / ``point_id_for``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.vector.base import (
    FilterDict,
    SearchResult,
    SparsePoint,
    VectorDocument,
)

if TYPE_CHECKING:
    from qdrant_client import models

logger = logging.getLogger(__name__)

# Named sparse vector used for every sparse collection created by this mixin.
BM25_SPARSE_VECTOR_NAME = "bm25"


def sparse_payload(point: SparsePoint) -> dict[str, object]:
    """Build the sparse-collection payload, mirroring the dense upsert layout.

    Keeping the payload shape identical (original_id / content / isoformat
    timestamps / epoch ts / metadata) lets the shared FilterDict semantics
    (namespace match, created_at ranges, archived flags) filter sparse results
    exactly like dense results.
    """
    return {
        "original_id": point.id,
        "content": point.content,
        "created_at": point.created_at.isoformat(),
        "updated_at": point.updated_at.isoformat(),
        "_created_ts": point.created_at.timestamp(),
        "_updated_ts": point.updated_at.timestamp(),
        **point.metadata,
    }


class QdrantSparseMixin:
    """Sparse-vector operations hosted by QdrantVectorStore.

    Hosts provide ``_client``, ``_with_retry`` and ``point_id_for``; the
    declarations below exist only for static analysis (runtime no-op).
    """

    if TYPE_CHECKING:
        _client: object

        def _execute(self, operation: object, *args: object, **kwargs: object) -> object: ...

        def _with_retry(self, operation: object, *args: object, **kwargs: object) -> object: ...

        def point_id_for(self, id_str: str) -> str: ...

    async def sparse_collection_ready(self, name: str) -> bool:
        """Return True when the sparse collection already exists."""
        try:
            # _execute adapts sync (embedded) and async (remote) clients alike.
            await self._execute(self._client.get_collection, collection_name=name)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    async def ensure_sparse_collection(self, name: str) -> bool:
        """Create a sparse-only collection. No-op if it already exists.

        Returns:
            True if created, False if it already existed.
        """
        if await self.sparse_collection_ready(name):
            return False

        from qdrant_client import models

        try:
            # Single-shot _execute (not _with_retry): the only expected failure
            # ("already exists" from a concurrent creator) must fail fast to the
            # except below, not burn the retry backoff on a deterministic 409.
            await self._execute(  # type: ignore[attr-defined]
                self._client.create_collection,  # type: ignore[union-attr]
                collection_name=name,
                sparse_vectors_config={
                    BM25_SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        index=models.SparseIndexParams(on_disk=False)
                    )
                },
            )
            return True
        except Exception as exc:
            # Concurrent creators may race past the readiness probe; Qdrant
            # answers 409 on existing collections, which is success for ensure.
            if "already exists" in str(exc).lower():
                return False
            raise

    async def upsert_sparse(self, collection: str, points: Sequence[SparsePoint]) -> list[str]:
        """Insert or update sparse points (idempotent replace per point id)."""
        from qdrant_client import models

        structs = [
            models.PointStruct(
                id=self.point_id_for(p.id),  # type: ignore[attr-defined]
                vector={
                    BM25_SPARSE_VECTOR_NAME: models.SparseVector(
                        indices=list(p.indices),
                        values=list(p.values),
                    )
                },
                payload=sparse_payload(p),
            )
            for p in points
        ]
        await self._with_retry(  # type: ignore[attr-defined]
            self._client.upsert,  # type: ignore[union-attr]
            collection_name=collection,
            points=structs,
        )
        return [p.id for p in points]

    async def search_sparse(
        self,
        collection: str,
        indices: list[int],
        values: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Query the ``bm25`` sparse vector with server-side IDF scoring."""
        from qdrant_client import models

        from myrm_agent_harness.toolkits.vector.qdrant.filters import build_qdrant_filter

        results = await self._with_retry(  # type: ignore[attr-defined]
            self._client.query_points,  # type: ignore[union-attr]
            collection_name=collection,
            query=models.SparseVector(indices=indices, values=values),
            using=BM25_SPARSE_VECTOR_NAME,
            query_filter=build_qdrant_filter(filters),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return [
            SearchResult(
                document=self._sparse_point_to_document(point),
                score=point.score,
            )
            for point in results.points  # type: ignore[union-attr]
        ]

    def _sparse_point_to_document(self, point: object) -> VectorDocument:
        """Convert a sparse-collection point back to a VectorDocument."""
        payload = dict(point.payload) if point.payload else {}  # type: ignore[union-attr]
        content = payload.pop("content", "")
        created_at_str = payload.pop("created_at", None)
        updated_at_str = payload.pop("updated_at", None)
        return VectorDocument(
            id=str(payload.pop("original_id", None) or point.id),  # type: ignore[union-attr]
            content=content,
            vector=None,
            metadata=payload,
            created_at=datetime.fromisoformat(created_at_str) if created_at_str else datetime.now(UTC),
            updated_at=datetime.fromisoformat(updated_at_str) if updated_at_str else datetime.now(UTC),
        )
