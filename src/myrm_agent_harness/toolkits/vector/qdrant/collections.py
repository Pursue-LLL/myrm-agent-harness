"""Qdrant Collection Lifecycle Operations.

[INPUT]
myrm_agent_harness.toolkits.vector.base (POS: CollectionInfo model)
qdrant_client (POS: Qdrant SDK, optional dependency)

[OUTPUT]
QdrantCollectionMixin: create / ensure / inspect / delete collections, payload indexes,
and epoch-timestamp backfill for QdrantVectorStore

[POS]
Collection-lifecycle layer for the Qdrant backend. Hosts every operation that only
touches collection shape (single-vector and named-vector creation, existence probes,
metadata, payload indexes, timestamp backfill) so the store core stays about data.
Mixins are hosted by QdrantVectorStore, which supplies ``_client`` / ``_config`` /
``_default_dimension`` / ``_execute`` / ``_with_retry``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.vector.base import CollectionInfo

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.vector.config import VectorStoreConfig

logger = logging.getLogger(__name__)


def _distance_of(distance: str) -> object:
    """Map a distance name onto the Qdrant enum, defaulting to cosine for unknown names."""
    from qdrant_client.models import Distance

    return {
        "cosine": Distance.COSINE,
        "euclidean": Distance.EUCLID,
        "dot": Distance.DOT,
    }.get(distance.lower(), Distance.COSINE)


class QdrantCollectionMixin:
    """Collection-lifecycle operations hosted by QdrantVectorStore.

    The host provides ``_client``, ``_config``, ``_default_dimension`` and the
    ``_execute`` / ``_with_retry`` adapters; the declarations below exist only for
    static analysis (runtime no-op) and mirror the host signatures exactly.
    """

    if TYPE_CHECKING:
        _client: object
        _config: VectorStoreConfig
        _default_dimension: int

        async def _execute(self, operation: object, *args: object, **kwargs: object) -> object: ...

        async def _with_retry(self, operation: object, *args: object, **kwargs: object) -> object: ...

    async def create_collection(
        self,
        name: str,
        dimension: int | None = None,
        distance: str = "cosine",
    ) -> bool:
        """Create a single-vector collection. No-op if it already exists."""
        from qdrant_client.models import VectorParams

        if await self.collection_exists(name):
            return False

        dim = dimension or self._default_dimension
        vectors_config = VectorParams(size=dim, distance=_distance_of(distance))
        created = await self._create_collection_with_vectors(name, vectors_config)
        logger.debug(
            f"Created collection: {name} (dim={dim}, distance={distance}, quant={self._quantization() is not None})"
        )
        return created

    async def create_named_vector_collection(
        self,
        name: str,
        dimension: int,
        *,
        names: Sequence[str],
        distance: str = "cosine",
    ) -> bool:
        """Create a collection whose points carry one vector per ``names`` entry.

        Each named vector is sized ``dimension``; ``get_collection_info`` reports no single
        size for such a collection, which is why ``ensure_collection`` skips its size check.
        """
        from qdrant_client.models import VectorParams

        if await self.collection_exists(name):
            return False

        vectors_config = {
            vector_name: VectorParams(size=dimension, distance=_distance_of(distance)) for vector_name in names
        }
        created = await self._create_collection_with_vectors(name, vectors_config)
        logger.debug(f"Created named-vector collection: {name} (vectors={list(names)}, dim={dimension})")
        return created

    async def _create_collection_with_vectors(self, name: str, vectors_config: object) -> bool:
        """Create ``name`` with a ready-made vectors config, so every creator shares retry and quantization."""
        create_kwargs: dict[str, object] = {
            "collection_name": name,
            "vectors_config": vectors_config,
        }
        quantization_config = self._quantization()
        if quantization_config is not None:
            create_kwargs["quantization_config"] = quantization_config

        await self._with_retry(
            self._client.create_collection,  # type: ignore[attr-defined]
            **create_kwargs,
        )
        return True

    def _quantization(self) -> object | None:
        """Scalar-quantization config for new collections, or None when disabled/unavailable."""
        if not getattr(self._config, "quantization_enabled", False):
            return None
        try:
            from qdrant_client.models import (
                ScalarQuantization,
                ScalarQuantizationConfig,
                ScalarType,
            )

            return ScalarQuantization(
                scalar=ScalarQuantizationConfig(
                    type=ScalarType.INT8,
                    always_ram=True,
                )
            )
        except Exception as e:
            logger.warning("Failed to configure Qdrant scalar quantization: %s", e)
            return None

    async def ensure_collection(
        self,
        name: str,
        dimension: int,
        *,
        distance: str = "cosine",
    ) -> None:
        """Idempotently create the collection when missing (VectorStoreProtocol contract).

        An existing collection whose vector size differs from ``dimension`` is refused instead of
        reused: every write into it would fail on the size check, and the mismatch means the
        collection holds another embedding model's vectors. Named-vector collections (raw /
        summary) carry no single size to compare, so ``get_collection_info`` reports nothing for
        them and validation is skipped.
        """
        if await self.collection_exists(name):
            info = await self.get_collection_info(name)
            if info is not None and info.dimension != dimension:
                raise ValueError(
                    f"Collection {name} holds {info.dimension}-dimensional vectors but {dimension} "
                    f"were requested; it belongs to another embedding model"
                )
            return
        await self.create_collection(name, dimension=dimension, distance=distance)

    async def delete_collection(self, name: str) -> bool:
        """Delete a collection, reporting whether it existed."""
        if not await self.collection_exists(name):
            return False
        await self._with_retry(self._client.delete_collection, collection_name=name)  # type: ignore[attr-defined]
        logger.debug(f"Deleted collection: {name}")
        return True

    async def collection_exists(self, name: str) -> bool:
        try:
            return await self._with_retry(self._client.collection_exists, collection_name=name)
        except Exception:
            return False

    async def get_collection_info(self, name: str) -> CollectionInfo | None:
        try:
            info = await self._execute(self._client.get_collection, collection_name=name)  # type: ignore[attr-defined]
            return CollectionInfo(
                name=name,
                dimension=info.config.params.vectors.size,  # type: ignore[union-attr]
                distance=info.config.params.vectors.distance.name.lower(),  # type: ignore[union-attr]
                count=info.points_count,
            )
        except Exception:
            return None

    async def list_collections(self) -> list[str]:
        collections = await self._execute(self._client.get_collections)  # type: ignore[attr-defined]
        return [c.name for c in collections.collections]  # type: ignore[union-attr]

    async def ensure_payload_indexes(self, collection: str) -> None:
        """Create payload indexes required for sorted scrolling and tag filtering.

        Idempotent — safe to call on every startup.  Indexes that already exist
        are silently skipped by Qdrant.
        """
        from qdrant_client.http.models import PayloadSchemaType

        index_specs: list[tuple[str, PayloadSchemaType]] = [
            ("_created_ts", PayloadSchemaType.FLOAT),
            ("_updated_ts", PayloadSchemaType.FLOAT),
            ("importance", PayloadSchemaType.FLOAT),
            ("tags", PayloadSchemaType.KEYWORD),
            ("namespaces", PayloadSchemaType.KEYWORD),
            ("primary_namespace", PayloadSchemaType.KEYWORD),
        ]
        for field, schema_type in index_specs:
            try:
                await self._with_retry(
                    self._client.create_payload_index,  # type: ignore[attr-defined]
                    collection_name=collection,
                    field_name=field,
                    field_schema=schema_type,
                )
            except Exception as e:
                logger.debug("Payload index %s on %s skipped: %s", field, collection, e)

    async def backfill_epoch_timestamps(self, collection: str, batch_size: int = 100) -> int:
        """Backfill ``_created_ts`` / ``_updated_ts`` for points missing them.

        Returns the number of points updated.
        """
        from qdrant_client.http.models import Filter, IsEmptyCondition, PayloadField

        missing_filter = Filter(must=[IsEmptyCondition(is_empty=PayloadField(key="_created_ts"))])
        updated = 0
        offset: str | None = None

        while True:
            points, next_offset = await self._with_retry(
                self._client.scroll,  # type: ignore[attr-defined]
                collection_name=collection,
                scroll_filter=missing_filter,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:  # type: ignore[truthy-bool]
                break
            for point in points:  # type: ignore[union-attr]
                payload = point.payload or {}
                iso_created = payload.get("created_at")
                iso_updated = payload.get("updated_at")
                if iso_created:
                    try:
                        ts = datetime.fromisoformat(iso_created).timestamp()
                    except (ValueError, TypeError):
                        ts = datetime.now(UTC).timestamp()
                else:
                    ts = datetime.now(UTC).timestamp()
                if iso_updated:
                    try:
                        uts = datetime.fromisoformat(iso_updated).timestamp()
                    except (ValueError, TypeError):
                        uts = ts
                else:
                    uts = ts
                await self._with_retry(
                    self._client.set_payload,  # type: ignore[attr-defined]
                    collection_name=collection,
                    payload={"_created_ts": ts, "_updated_ts": uts},
                    points=[point.id],
                )
                updated += 1
            if next_offset is None:
                break
            offset = str(next_offset)

        if updated:
            logger.info(
                "Backfilled %d points in collection %s with epoch timestamps",
                updated,
                collection,
            )
        return updated
