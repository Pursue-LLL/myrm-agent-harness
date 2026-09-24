"""Wiki FTS/vector index operations (SQLite FTS5 + Qdrant hybrid search).

[INPUT]
- sqlite3 (POS: standard library database)
- myrm_agent_harness.toolkits.retriever.cjk_tokenizer::build_cjk_index_segment (POS: FTS CJK write-side token segment builder)
- myrm_agent_harness.toolkits.retriever.embedding.window_policy::EmbedInputTooLargeError (POS: embedding input window violation)
- myrm_agent_harness.toolkits.retriever.fusion_strategies::rrf_fusion (POS: result fusion strategy)
- myrm_agent_harness.utils.db.fts5::fts5_auto_heal (POS: FTS5 corruption auto-heal helper)
- myrm_agent_harness.utils.markdown_frontmatter::parse_frontmatter (POS: frontmatter parser)
- ..core.frontmatter_contract::WikiPublishStatus (POS: publish_status SSOT)
- .sidecar_index::_SIDECAR_PREFIX (POS: L0/L1 sidecar index operations)
- .tokenizer::tokenize_for_fts (POS: FTS5 query tokenizer)
- .vector_chunks::collapse_vector_hits, delete_text_vectors, upsert_text_vectors (POS: L2 chunk vector operations)

[OUTPUT]
- FtsSearchMixin: FTS5 + vector upsert/search/get_truth for WikiIndexer
- migrate_wiki_fts_schema: rebuild wiki_fts when it predates the search_terms column

[POS]
Wiki index write/read operations mixin. Keeps FTS truth storage, hybrid search
fusion and vector indexing out of the indexer to preserve single-responsibility
module sizing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import sqlite3
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.cjk_tokenizer import build_cjk_index_segment
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedInputTooLargeError,
)
from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.utils.db.fts5 import fts5_auto_heal
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

from ..core.config import WikiConfig
from ..core.frontmatter_contract import (
    PUBLISH_STATUS_KEY,
    WIKI_PUBLISH_STATUSES,
    WikiPublishStatus,
)
from .sidecar_index import _SIDECAR_PREFIX
from .tokenizer import tokenize_for_fts
from .vector_chunks import (
    collapse_vector_hits,
    delete_text_vectors,
    upsert_text_vectors,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractContextManager

    from myrm_agent_harness.toolkits.memory.protocols.embedding import (
        EmbeddingProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

    from ..core.structure import WikiStructure

logger = logging.getLogger(__name__)


class FtsSearchMixin:
    """FTS5 truth storage plus vector upsert/search operations for WikiIndexer.

    Expects the host class to provide: _get_conn, _config, _vector, _embedding,
    _collection_name, _ensure_collection, _structure, _is_sidecar_entry and
    _concept_dir_path.
    """

    _config: WikiConfig
    _vector: VectorStoreProtocol | None
    _embedding: EmbeddingProtocol | None
    _collection_name: str

    if TYPE_CHECKING:
        # Attributes provided by the host class (WikiIndexer); only for type checking.
        _get_conn: Callable[[], AbstractContextManager[sqlite3.Connection]]
        _structure: WikiStructure
        _ensure_collection: Callable[[], Awaitable[None]]
        _is_sidecar_entry: Callable[[str], bool]
        _concept_dir_path: Callable[[str], str]

    def remove_raw_text_index(self, name: str) -> None:
        """Remove interim raw FTS entry (see :meth:`index_raw_text`)."""
        raw_key = f"raw:{name}"
        with self._get_conn() as conn:
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (raw_key,))

    def index_raw_text(self, name: str, text: str) -> None:
        """Index raw text into FTS5 for immediate searchability before compilation.

        Uses a ``raw:`` prefix to distinguish from compiled entries. When the
        compiled version is later upserted via :meth:`upsert`, it replaces
        this interim entry.
        """
        raw_key = f"raw:{name}"
        preview = text[:5000] if len(text) > 5000 else text
        indexed_content = build_cjk_index_segment(f"{name} {preview}")

        with self._get_conn() as conn:
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (raw_key,))
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content, search_terms) VALUES (?, ?, ?)",
                (raw_key, preview, indexed_content),
            )

    @staticmethod
    def _resolve_publish_status(full_markdown: str) -> str:
        metadata, _body = parse_frontmatter(full_markdown)
        status = str(metadata.get(PUBLISH_STATUS_KEY, "")).strip().lower()
        if status in WIKI_PUBLISH_STATUSES:
            return status
        return WikiPublishStatus.PUBLISHED.value

    def _is_published(self, conn: sqlite3.Connection, concept_name: str) -> bool:
        cursor = conn.execute(
            "SELECT publish_status FROM wiki_index_meta WHERE concept_name = ?",
            (concept_name,),
        )
        row = cursor.fetchone()
        if row is not None:
            return str(row["publish_status"]) == WikiPublishStatus.PUBLISHED.value

        # Check attached federated public databases
        attached_dbs = {str(r["name"]) for r in conn.execute("PRAGMA database_list").fetchall()}
        for idx in range(min(len(self._structure.public_dirs), 6)):
            alias = f"pub_{idx}"
            if alias in attached_dbs:
                try:
                    c = conn.execute(
                        f"SELECT publish_status FROM {alias}.wiki_index_meta WHERE concept_name = ?",
                        (concept_name,),
                    )
                    r = c.fetchone()
                    if r is not None:
                        return str(r["publish_status"]) == WikiPublishStatus.PUBLISHED.value
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    continue
        return True

    def _filter_published(self, conn: sqlite3.Connection, results: list[tuple[str, float]]) -> list[tuple[str, float]]:
        return [(name, score) for name, score in results if self._is_published(conn, name)]

    async def upsert(self, concept_name: str, full_markdown: str) -> None:
        """
        Extract Compiled Truth and upsert into FTS5 index and Vector Store.
        """
        truth_content = self._extract_truth(full_markdown)
        publish_status = self._resolve_publish_status(full_markdown)

        def sync_upsert() -> None:
            search_terms = build_cjk_index_segment(f"{concept_name} {truth_content}")
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (concept_name,))
                conn.execute(
                    "DELETE FROM wiki_fts WHERE concept_name = ?",
                    (f"raw:{concept_name}",),
                )
                conn.execute(
                    "INSERT INTO wiki_fts (concept_name, truth_content, search_terms) VALUES (?, ?, ?)",
                    (concept_name, truth_content, search_terms),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO wiki_index_meta (concept_name, publish_status) VALUES (?, ?)",
                    (concept_name, publish_status),
                )
            if hasattr(self, "extract_and_upsert_edges"):
                try:
                    self.extract_and_upsert_edges(concept_name, full_markdown)
                except Exception as e:
                    logger.warning("Failed to extract edges for %s: %s", concept_name, e)

        await asyncio.to_thread(sync_upsert)

        # 2. Upsert to Vector Store (Async) — published entries only
        if (
            publish_status == WikiPublishStatus.PUBLISHED.value
            and self._config.enable_hybrid_search
            and self._vector
            and self._embedding
        ):
            await self._ensure_collection()
            try:
                await upsert_text_vectors(
                    embedding=self._embedding,
                    vector=self._vector,
                    collection_name=self._collection_name,
                    parent_key=concept_name,
                    text=truth_content,
                    base_metadata={
                        "concept_name": concept_name,
                        "entry_type": "concept",
                        "level": "L2",
                        "dir_path": self._concept_dir_path(concept_name),
                    },
                    metadata_key="concept_name",
                )
            except EmbedInputTooLargeError:
                # Window violations must surface (reindex layer reports them); other
                # vector failures degrade gracefully to FTS-only.
                raise
            except Exception as e:
                logger.warning(f"Vector upsert failed for wiki concept '{concept_name}', keeping FTS only: {e}")

    async def delete(self, concept_name: str) -> None:
        """
        Delete concept from FTS5 index, Edges, and Vector Store.
        """

        # 1. Delete from SQLite FTS5 and edges (Sync wrapped in async thread)
        def sync_delete() -> None:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (concept_name,))
                conn.execute(
                    "DELETE FROM wiki_edges WHERE source = ? OR target = ?",
                    (concept_name, concept_name),
                )
                conn.execute(
                    "DELETE FROM wiki_index_meta WHERE concept_name = ?",
                    (concept_name,),
                )

        await asyncio.to_thread(sync_delete)

        # 2. Delete from Vector Store (Async)
        if self._config.enable_hybrid_search and self._vector:
            try:
                await delete_text_vectors(
                    self._vector,
                    self._collection_name,
                    concept_name,
                    metadata_key="concept_name",
                )
            except Exception as e:
                logger.error(f"Failed to delete vector for wiki concept '{concept_name}': {e}")

    async def search(self, query: str, limit: int = 5, offset: int = 0) -> list[tuple[str, float]]:
        """
        Search the index and return (concept_name, score).
        If Hybrid Search is enabled, performs FTS5 + Vector search and fuses via RRF.
        Returns a sorted list by score (higher is better).
        """
        safe_query = query.replace('"', "").replace("'", "").strip()
        if not safe_query:
            return []

        # 1. FTS5 Search
        fts_results: list[tuple[str, float]] = []

        def sync_fts_search() -> list[tuple[str, float]]:
            results = []
            with self._get_conn() as conn:
                try:
                    fts_tables = ["wiki_fts"]
                    attached_dbs = {str(row["name"]) for row in conn.execute("PRAGMA database_list").fetchall()}
                    for idx in range(min(len(self._structure.public_dirs), 6)):
                        alias = f"pub_{idx}"
                        if alias in attached_dbs:
                            try:
                                has_table = conn.execute(
                                    f"SELECT 1 FROM {alias}.sqlite_master WHERE type IN ('table', 'view') AND name = 'wiki_fts'"
                                ).fetchone()
                                if has_table:
                                    fts_tables.append(f"{alias}.wiki_fts")
                            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                                continue

                    fts_query = tokenize_for_fts(safe_query)

                    if fts_query:
                        # In SQLite FTS5, the MATCH operator can be used on the table name.
                        # e.g., pub_0.wiki_fts MATCH ? is valid, but the column name inside WHERE is wiki_fts MATCH ?
                        fts_union = " UNION ALL ".join(
                            (
                                f"SELECT concept_name, rank, '{t}' AS src_tbl FROM {t} "
                                f"WHERE {t.split('.')[-1]} MATCH ? "
                                f"AND concept_name NOT GLOB '{_SIDECAR_PREFIX}:*'"
                            )
                            for t in fts_tables
                        )
                        params = (fts_query,) * len(fts_tables)

                        cursor = conn.execute(
                            f"""
                            SELECT concept_name, rank, src_tbl
                            FROM ({fts_union})
                            ORDER BY rank
                            LIMIT ? OFFSET ?
                            """,
                            (*params, limit * 2, offset),  # Fetch more for fusion
                        )

                        for row in cursor.fetchall():
                            if self._is_sidecar_entry(str(row["concept_name"])):
                                continue
                            # FTS5 rank is negative, lower is better. We invert it for RRF fusion.
                            # Primary vault has decay=1.0; attached federated public vaults receive 0.9 to prevent generic terms from overtaking primary truths.
                            decay = 0.9 if str(row["src_tbl"]).startswith("pub_") else 1.0
                            score = (1.0 / (abs(row["rank"]) + 1.0)) * decay
                            results.append((row["concept_name"], score))
                    results[:] = self._filter_published(conn, results)
                except sqlite3.OperationalError as e:
                    logger.error(f"FTS search error: {e}")
                    healed = fts5_auto_heal(conn, "wiki_fts")
                    if healed and fts_query:
                        logger.info("FTS5 auto-heal succeeded, retrying search")
                        with contextlib.suppress(sqlite3.OperationalError):
                            cursor = conn.execute(
                                f"""
                                SELECT concept_name, rank, src_tbl
                                FROM ({fts_union})
                                ORDER BY rank
                                LIMIT ? OFFSET ?
                                """,
                                (*params, limit * 2, offset),
                            )
                            for row in cursor.fetchall():
                                if self._is_sidecar_entry(str(row["concept_name"])):
                                    continue
                                decay = 0.9 if str(row["src_tbl"]).startswith("pub_") else 1.0
                                score = (1.0 / (abs(row["rank"]) + 1.0)) * decay
                                results.append((row["concept_name"], score))
                        results[:] = self._filter_published(conn, results)
            return results

        fts_results = await asyncio.to_thread(sync_fts_search)

        # 2. Vector Search (if enabled)
        vec_results: list[tuple[str, float]] = []
        if self._config.enable_hybrid_search and self._vector and self._embedding:
            await self._ensure_collection()
            try:
                query_vec = await self._embedding.embed(query)
                # Note: VectorStore search doesn't natively support offset, we slice the result
                search_limit = limit + offset
                search_res = await self._vector.search(
                    self._collection_name, query_vector=query_vec, limit=search_limit
                )
                for res in search_res[offset:]:
                    candidate = str(res.document.metadata.get("concept_name", res.document.id))
                    if self._is_sidecar_entry(candidate):
                        continue
                    vec_results.append((candidate, res.score))
            except EmbedInputTooLargeError:
                raise
            except Exception as e:
                logger.error(f"Wiki vector search failed: {e}")

        vec_results = collapse_vector_hits(vec_results)

        if vec_results:

            def sync_filter_vec(
                results: list[tuple[str, float]],
            ) -> list[tuple[str, float]]:
                with self._get_conn() as conn:
                    return self._filter_published(conn, results)

            vec_results = await asyncio.to_thread(sync_filter_vec, vec_results)

        # 3. Hybrid Fusion (RRF)
        if self._config.enable_hybrid_search and self._vector and self._embedding:
            if fts_results or vec_results:
                final_results = rrf_fusion([fts_results, vec_results], k=getattr(self._config, "rrf_k", 60))
            else:
                final_results = []
        else:
            final_results = fts_results

        # Sort and truncate
        final_results.sort(key=lambda x: x[1], reverse=True)
        return final_results[:limit]

    def get_truth(self, concept_name: str) -> str | None:
        """Get the cached truth content for context injection (published entries only)."""
        with self._get_conn() as conn:
            if not self._is_published(conn, concept_name):
                return None
            fts_tables = ["wiki_fts"]
            attached_dbs = {str(row["name"]) for row in conn.execute("PRAGMA database_list").fetchall()}
            for idx in range(min(len(self._structure.public_dirs), 6)):
                alias = f"pub_{idx}"
                if alias in attached_dbs:
                    try:
                        has_table = conn.execute(
                            f"SELECT 1 FROM {alias}.sqlite_master WHERE type IN ('table', 'view') AND name = 'wiki_fts'"
                        ).fetchone()
                        if has_table:
                            fts_tables.append(f"{alias}.wiki_fts")
                    except (sqlite3.OperationalError, sqlite3.DatabaseError):
                        continue

            fts_union = " UNION ALL ".join(f"SELECT truth_content FROM {t} WHERE concept_name = ?" for t in fts_tables)
            params = (concept_name,) * len(fts_tables)

            cursor = conn.execute(fts_union, params)
            row = cursor.fetchone()
            return row["truth_content"] if row else None

    @staticmethod
    def _extract_truth(content: str) -> str:
        """Extract only YAML and Compiled Truth from full markdown."""
        truth_content = ""

        # 1. Extract YAML
        yaml_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if yaml_match:
            truth_content += f"---\n{yaml_match.group(1)}\n---\n\n"

        # 2. Extract Truth section
        truth_match = re.search(r"(## Compiled Truth\n.*?)(?=\n## |$)", content, re.DOTALL)
        if truth_match:
            truth_content += truth_match.group(1).strip()
        else:
            # Fallback
            truth_content = content

        return truth_content


def migrate_wiki_fts_schema(conn: sqlite3.Connection) -> None:
    """Rebuild wiki_fts when it predates the ``search_terms`` column.

    FTS5 virtual tables cannot be altered in place and the index is a
    rebuildable cache, so legacy rows keep their existing search text in both
    columns while new upserts store the original truth plus segmented terms.
    """
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(wiki_fts)").fetchall()}
    if "search_terms" in columns:
        return

    logger.info("Migrating wiki_fts to the truth_content + search_terms schema")
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts_v2 USING fts5(
            concept_name,
            truth_content,
            search_terms,
            tokenize="unicode61 remove_diacritics 1"
        )
    """
    )
    conn.execute(
        "INSERT INTO wiki_fts_v2 (concept_name, truth_content, search_terms) "
        "SELECT concept_name, truth_content, truth_content FROM wiki_fts"
    )
    conn.execute("DROP TABLE wiki_fts")
    conn.execute("ALTER TABLE wiki_fts_v2 RENAME TO wiki_fts")
