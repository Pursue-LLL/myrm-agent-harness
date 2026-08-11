"""Sidecar indexing mixin for WikiIndexer.

[INPUT]
asyncio (POS: standard library async utilities)
contextlib (POS: standard library context utilities)
uuid (POS: standard library UUID generation)
..core.config::WikiConfig (POS: Wiki configuration center)
myrm_agent_harness.toolkits.vector.base::VectorDocument (POS: vector document)
myrm_agent_harness.toolkits.retriever.fusion_strategies::rrf_fusion (POS: result fusion strategy)
.tokenizer::tokenize_for_fts (POS: FTS5 query tokenizer)

[OUTPUT]
SidecarIndexMixin: L0/L1 directory sidecar index operations (upsert, delete, search)

[POS]
Mixin providing sidecar (L0/L1 directory summary) indexing operations for WikiIndexer.
Manages FTS5 + Qdrant hybrid indexing of hierarchical directory sidecars, keeping
sidecar entries cleanly separated from L2 concept entries via prefixed entry IDs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion

from ..core.config import WikiConfig
from .tokenizer import tokenize_for_fts
from .vector_chunks import delete_text_vectors, upsert_text_vectors

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

_SIDECAR_PREFIX = "__sidecar__"
_SIDECAR_ROOT = "__root__"
_SIDECAR_LEVEL_LABEL = {
    0: "L0",
    1: "L1",
}


class SidecarIndexMixin:
    """Mixin providing L0/L1 sidecar indexing and search for WikiIndexer.

    Expects the host class to provide: _get_conn, _config, _vector, _embedding,
    _collection_name, _collection_ready, _ensure_collection, _structure.
    """

    _config: WikiConfig
    _vector: VectorStoreProtocol | None
    _embedding: EmbeddingProtocol | None
    _collection_name: str
    _collection_ready: bool

    @staticmethod
    def _normalize_dir_path(dir_path: str) -> str:
        return dir_path.strip().replace("\\", "/").strip("/")

    @staticmethod
    def _concept_dir_path(concept_name: str) -> str:
        normalized = concept_name.strip().replace("\\", "/").strip("/")
        if "/" not in normalized:
            return ""
        return normalized.rsplit("/", 1)[0]

    @staticmethod
    def _is_sidecar_entry(entry_id: str) -> bool:
        return entry_id.startswith(f"{_SIDECAR_PREFIX}:")

    def _sidecar_entry_id(self, dir_path: str, level: int) -> str:
        if level not in _SIDECAR_LEVEL_LABEL:
            raise ValueError(f"Unsupported sidecar level: {level}")
        normalized = self._normalize_dir_path(dir_path)
        token = normalized if normalized else _SIDECAR_ROOT
        return f"{_SIDECAR_PREFIX}:{_SIDECAR_LEVEL_LABEL[level]}:{token}"

    @staticmethod
    def _decode_sidecar_entry_id(entry_id: str) -> tuple[str, int] | None:
        if not entry_id.startswith(f"{_SIDECAR_PREFIX}:"):
            return None
        parts = entry_id.split(":", 2)
        if len(parts) != 3:
            return None
        _, level_label, token = parts
        level = 0 if level_label == "L0" else 1 if level_label == "L1" else None
        if level is None:
            return None
        dir_path = "" if token == _SIDECAR_ROOT else token
        return dir_path, level

    @staticmethod
    def _concept_to_uuid(concept_name: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_OID, concept_name))

    async def upsert_sidecar(self, dir_path: str, *, level: int, content: str) -> None:
        """Upsert directory sidecar content (L0/L1) into FTS + vector index."""
        if level not in _SIDECAR_LEVEL_LABEL:
            raise ValueError(f"Unsupported sidecar level: {level}")
        entry_id = self._sidecar_entry_id(dir_path, level)
        normalized_dir = self._normalize_dir_path(dir_path)
        payload = content.strip()
        if not payload:
            payload = "No validated knowledge yet for this directory."

        def sync_upsert():
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (entry_id,))
                conn.execute(
                    "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                    (entry_id, payload),
                )

        await asyncio.to_thread(sync_upsert)

        if self._config.enable_hybrid_search and self._vector and self._embedding:
            await self._ensure_collection()
            try:
                await upsert_text_vectors(
                    embedding=self._embedding,
                    vector=self._vector,
                    collection_name=self._collection_name,
                    parent_key=entry_id,
                    text=payload,
                    base_metadata={
                        "concept_name": entry_id,
                        "entry_type": "sidecar",
                        "level": _SIDECAR_LEVEL_LABEL[level],
                        "dir_path": normalized_dir,
                    },
                    metadata_key="concept_name",
                )
            except Exception as e:
                logger.warning(f"Sidecar vector upsert failed for '{entry_id}', keeping FTS only: {e}")

    async def delete_sidecar(self, dir_path: str, *, level: int) -> None:
        """Delete one directory sidecar entry from FTS + vector index."""
        entry_id = self._sidecar_entry_id(dir_path, level)

        def sync_delete():
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (entry_id,))

        await asyncio.to_thread(sync_delete)
        if self._config.enable_hybrid_search and self._vector:
            with contextlib.suppress(Exception):
                await delete_text_vectors(
                    self._vector,
                    self._collection_name,
                    entry_id,
                    metadata_key="concept_name",
                )

    async def delete_all_sidecars(self) -> None:
        """Delete all sidecar entries from FTS + vector index."""

        def sync_delete_all():
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM wiki_fts WHERE concept_name GLOB ?",
                    (f"{_SIDECAR_PREFIX}:*",),
                )

        await asyncio.to_thread(sync_delete_all)
        if self._config.enable_hybrid_search and self._vector:
            with contextlib.suppress(Exception):
                await self._vector.delete_by_filter(
                    self._collection_name,
                    {"entry_type": "sidecar"},
                )

    def get_sidecar_truth(self, dir_path: str, *, level: int) -> str | None:
        """Get indexed sidecar content by directory and level."""
        entry_id = self._sidecar_entry_id(dir_path, level)
        return self.get_truth(entry_id)

    async def search_sidecars(
        self,
        query: str,
        *,
        levels: tuple[int, ...] = (0, 1),
        limit: int = 8,
    ) -> list[tuple[str, int, float]]:
        """Search L0/L1 sidecars and return ranked (dir_path, level, score)."""
        safe_query = query.replace('"', "").replace("'", "").strip()
        if not safe_query:
            return []
        allowed_levels = tuple(sorted({lvl for lvl in levels if lvl in _SIDECAR_LEVEL_LABEL}))
        if not allowed_levels:
            return []

        fts_results: list[tuple[str, float]] = []

        def sync_fts_search() -> list[tuple[str, float]]:
            with self._get_conn() as conn:
                fts_query = tokenize_for_fts(safe_query)
                if not fts_query:
                    return []
                fts_tables = ["wiki_fts"]
                for idx, p_dir in enumerate(self._structure.public_dirs):
                    pub_db = p_dir / ".wiki_index.db"
                    if pub_db.exists():
                        fts_tables.append(f"pub_{idx}.wiki_fts")
                sidecar_filters = " OR ".join(["concept_name GLOB ?"] * len(allowed_levels))
                patterns = tuple(
                    f"{_SIDECAR_PREFIX}:{_SIDECAR_LEVEL_LABEL[level]}:*"
                    for level in allowed_levels
                )
                union_queries = " UNION ALL ".join(
                    (
                        f"SELECT concept_name, rank FROM {table} "
                        f"WHERE ({sidecar_filters}) AND {table.split('.')[-1]} MATCH ?"
                    )
                    for table in fts_tables
                )
                params: list[str] = []
                for _ in fts_tables:
                    params.extend(patterns)
                    params.append(fts_query)
                cursor = conn.execute(
                    f"SELECT concept_name, rank FROM ({union_queries}) ORDER BY rank LIMIT ?",
                    (*params, limit * 2),
                )
                rows: list[tuple[str, float]] = []
                for row in cursor.fetchall():
                    score = 1.0 / (abs(row["rank"]) + 1.0)
                    rows.append((row["concept_name"], score))
                return rows

        with contextlib.suppress(Exception):
            fts_results = await asyncio.to_thread(sync_fts_search)

        vec_results: list[tuple[str, float]] = []
        if self._config.enable_hybrid_search and self._vector and self._embedding:
            await self._ensure_collection()
            try:
                query_vec = await self._embedding.embed(query)
            except Exception:
                query_vec = None
            vector_hits = []
            if query_vec is not None:
                try:
                    vector_hits = await self._vector.search(
                        self._collection_name,
                        query_vector=query_vec,
                        limit=limit * 2,
                        filters={
                            "entry_type": "sidecar",
                            "level": [_SIDECAR_LEVEL_LABEL[level] for level in allowed_levels],
                        },
                    )
                except Exception:
                    with contextlib.suppress(Exception):
                        vector_hits = await self._vector.search(
                            self._collection_name,
                            query_vector=query_vec,
                            limit=limit * 2,
                        )
            for hit in vector_hits:
                concept_name = str(hit.document.metadata.get("concept_name", "")).strip()
                if not concept_name or not self._is_sidecar_entry(concept_name):
                    continue
                decoded = self._decode_sidecar_entry_id(concept_name)
                if decoded is None:
                    continue
                _dir, level = decoded
                if level not in allowed_levels:
                    continue
                vec_results.append((concept_name, hit.score))

        if fts_results or vec_results:
            ranked = rrf_fusion([fts_results, vec_results], k=getattr(self._config, "rrf_k", 60))
        else:
            ranked = []

        out: list[tuple[str, int, float]] = []
        for entry_id, score in ranked:
            decoded = self._decode_sidecar_entry_id(entry_id)
            if decoded is None:
                continue
            dir_path, level = decoded
            out.append((dir_path, level, score))
            if len(out) >= limit:
                break
        return out
