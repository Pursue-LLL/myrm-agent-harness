"""Wiki Indexer - SQLite FTS5 + Qdrant RRF based Hybrid search engine.

[INPUT]
- sqlite3 (POS: standard library database)
- ..core.structure::WikiStructure (POS: database path resolution)
- ..core.config::WikiConfig (POS: Wiki configuration)
- ..core.frontmatter_contract::WikiPublishStatus (POS: publish_status SSOT)
- myrm_agent_harness.toolkits.vector.base::VectorDocument (POS: vector document)
- myrm_agent_harness.toolkits.retriever.fusion_strategies::rrf_fusion (POS: result fusion strategy)
- .tokenizer::tokenize_for_fts (POS: FTS5 query tokenizer)
- .graph_store::WikiGraphStore (POS: knowledge graph storage)
- .sidecar_index::SidecarIndexMixin (POS: L0/L1 sidecar index operations)

[OUTPUT]
- WikiIndexer: hybrid search engine; wiki_index_meta publish_status gate for FTS/vector/get_truth

[POS]
Wiki concept indexer core. Manages FTS5 + Qdrant hybrid search for L2 concept entries,
knowledge graph edges, and federated multi-database queries. Only `publish_status=published`
entries are searchable and vector-indexed. Sidecar (L0/L1) indexing operations are provided
by SidecarIndexMixin to keep this file focused on concept-level indexing.
"""

import asyncio
import contextlib
import logging
import re
import sqlite3
from collections.abc import Iterator
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedInputTooLargeError,
)
from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.utils.db.fts5 import (
    fts5_auto_heal,
    fts5_integrity_check,
    fts5_rebuild,
)
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

from ..core.config import WikiConfig
from ..core.frontmatter_contract import (
    PUBLISH_STATUS_KEY,
    WIKI_PUBLISH_STATUSES,
    WikiPublishStatus,
)
from ..core.structure import WikiStructure
from .graph_store import WikiGraphStore
from .sidecar_index import _SIDECAR_PREFIX, SidecarIndexMixin
from .tokenizer import tokenize_for_fts
from myrm_agent_harness.toolkits.retriever.cjk_tokenizer import build_cjk_index_segment
from .vector_chunks import (
    collapse_vector_hits,
    delete_text_vectors,
    upsert_text_vectors,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)


class WikiIndexer(SidecarIndexMixin):
    """
    SQLite FTS5 + Qdrant Vector powered indexer for Wiki articles.

    Provides milliseconds latency hybrid search and ensures Agent RAG
    only sees the `Compiled Truth` to protect prompt caching.
    """

    def __init__(
        self,
        structure: WikiStructure,
        config: WikiConfig | None = None,
        vector_store: "VectorStoreProtocol | None" = None,
        embedding: "EmbeddingProtocol | None" = None,
    ):
        self._structure = structure
        self._config = config or WikiConfig()
        self._vector = vector_store
        self._embedding = embedding
        self.db_path = self._structure.base_dir / ".wiki_index.db"
        self._collection_name = "wiki_concepts"
        self._collection_ready = False
        self._init_db()
        self._graph_store = WikiGraphStore(self._get_conn, structure)

    @contextlib.contextmanager
    def _get_conn(self) -> Iterator[sqlite3.Connection]:
        from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

        conn = sqlite3.connect(self.db_path, uri=True)
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, CACHE, db_path=self.db_path)

        # Dynamically ATTACH federated public databases (Read-Only via SQLite URI protocol)
        # Cap at 6 to strictly protect SQLite ATTACH limits and system file descriptors.
        attached_count = 0
        for idx, p_dir in enumerate(self._structure.public_dirs):
            if attached_count >= 6:
                logger.warning(
                    "Reached maximum federated public dirs attachment limit (6), skipping remaining."
                )
                break
            try:
                pub_db = p_dir / ".wiki_index.db"
                if pub_db.is_file():
                    # Use file:...URI with mode=ro to strictly prevent OperationalError in read-only volumes
                    # and ensure non-destructive mounting of shared organizational vaults.
                    safe_uri = f"file:{pub_db.resolve().as_posix()}?mode=ro"
                    conn.execute(f"ATTACH DATABASE ? AS pub_{idx}", (safe_uri,))
                    attached_count += 1
            except (sqlite3.Error, OSError) as e:
                logger.warning(f"Failed to attach federated database {p_dir}: {e}")

        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            # Use FTS5 for full-text search
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
                    concept_name,
                    truth_content,
                    tokenize="unicode61 remove_diacritics 1"
                )
            """
            )
            # 增量 O(1) 图谱双链关系表 (Holographic Graph Persistence)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wiki_edges(
                    source TEXT,
                    target TEXT,
                    weight REAL DEFAULT 1.0,
                    PRIMARY KEY (source, target)
                )
            """
            )
            # Migrate: add weight column to existing tables created before this version
            # (OperationalError means the column already exists).
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    "ALTER TABLE wiki_edges ADD COLUMN weight REAL DEFAULT 1.0"
                )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_wiki_edges_target ON wiki_edges(target)
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wiki_index_meta(
                    concept_name TEXT PRIMARY KEY,
                    publish_status TEXT NOT NULL DEFAULT 'published'
                )
            """
            )

            if not fts5_integrity_check(conn, "wiki_fts"):
                logger.warning("FTS5 index corrupted on startup, rebuilding: wiki_fts")
                fts5_rebuild(conn, "wiki_fts")

    def get_knowledge_graph(
        self, center_node: str | None = None, depth: int = 1, limit: int = 1000
    ) -> dict[str, list[dict[str, object]]]:
        """Delegate to WikiGraphStore for BFS graph traversal."""
        return self._graph_store.get_knowledge_graph(center_node, depth, limit)

    def graph_insights(self) -> dict[str, list[dict[str, object]]]:
        """Delegate to WikiGraphStore for graph structural analysis."""
        return self._graph_store.graph_insights()

    def get_outgoing_edges(self, source: str) -> list[tuple[str, float]]:
        """Return weighted outgoing graph edges for a concept, highest weight first."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT target, weight FROM wiki_edges WHERE source = ? ORDER BY weight DESC",
                (source,),
            )
            return [
                (str(row["target"]), float(row["weight"])) for row in cursor.fetchall()
            ]

    def upsert_edges(
        self, source: str, targets: list[str], source_files: list[str] | None = None
    ) -> None:
        """Upsert directional edges with multi-dimensional weight calculation."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM wiki_edges WHERE source = ?", (source,))
            for target in targets:
                if source == target:
                    continue
                weight = self._calculate_edge_weight(conn, source, target, source_files)
                conn.execute(
                    "INSERT OR REPLACE INTO wiki_edges (source, target, weight) VALUES (?, ?, ?)",
                    (source, target, weight),
                )

    def _calculate_edge_weight(
        self,
        conn: sqlite3.Connection,
        source: str,
        target: str,
        source_files: list[str] | None,
    ) -> float:
        """
        Multi-dimensional edge weight: direct_link(3.0) + source_overlap(4.0) + common_neighbors(1.5).
        """
        weight = 3.0  # Base weight for direct link existence

        # Source overlap: check if target's sources overlap with source's
        if source_files:
            cursor = conn.execute(
                "SELECT source FROM wiki_edges WHERE target = ? LIMIT 20", (target,)
            )
            target_neighbors = {row["source"] for row in cursor.fetchall()}
            # If target links back to concepts that share source files, add overlap bonus
            if target_neighbors:
                weight += min(len(target_neighbors) * 0.5, 4.0)

        # Common neighbors (Adamic-Adar inspired): shared connections indicate relatedness
        cursor = conn.execute(
            "SELECT target FROM wiki_edges WHERE source = ?", (source,)
        )
        source_neighbors = {row["target"] for row in cursor.fetchall()}
        cursor = conn.execute(
            "SELECT target FROM wiki_edges WHERE source = ?", (target,)
        )
        target_out_neighbors = {row["target"] for row in cursor.fetchall()}

        common = source_neighbors & target_out_neighbors
        if common:
            weight += min(len(common) * 0.5, 1.5)

        return round(weight, 2)

    def extract_and_upsert_edges(self, concept_name: str, content: str) -> None:
        """Parse markdown links and Wikilinks, then upsert to SQLite edges table."""
        targets = []

        # 1. Match Standard Markdown Links: [text](link.md)
        links = re.findall(r"\[([^\]]+)\]\(([^)]+)\.md\)", content)
        targets.extend([t.strip() for _, t in links if t.strip()])

        # 2. Match Obsidian Wikilinks: [[link]] or [[link|alias]]
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        for wl in wikilinks:
            target = wl.split("|")[0].strip()
            if target:
                targets.append(target)

        targets = list(set(targets))

        # Unconditionally upsert (even if empty) to clear deleted edges
        self.upsert_edges(concept_name, targets)

    async def _ensure_collection(self) -> None:
        """Lazily initialize vector collection if vector store is enabled."""
        if not self._vector or not self._embedding or self._collection_ready:
            return
        try:
            # Need to get dimension from dummy embedding
            test_vec = await self._embedding.embed("test")
            dim = len(test_vec)

            if hasattr(self._vector, "ensure_collection"):
                await self._vector.ensure_collection(self._collection_name, dim)
            elif hasattr(self._vector, "create_collection"):
                # fallback for older Protocol implementations
                exists = await self._vector.collection_exists(self._collection_name)
                if not exists:
                    await self._vector.create_collection(self._collection_name, dim)
            self._collection_ready = True
        except Exception as e:
            logger.warning(f"Failed to ensure wiki vector collection: {e}")

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
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                (raw_key, indexed_content),
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
        attached_dbs = {
            str(r["name"]) for r in conn.execute("PRAGMA database_list").fetchall()
        }
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
                        return (
                            str(r["publish_status"])
                            == WikiPublishStatus.PUBLISHED.value
                        )
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    continue
        return True

    def _filter_published(
        self, conn: sqlite3.Connection, results: list[tuple[str, float]]
    ) -> list[tuple[str, float]]:
        return [
            (name, score) for name, score in results if self._is_published(conn, name)
        ]

    async def upsert(self, concept_name: str, full_markdown: str) -> None:
        """
        Extract Compiled Truth and upsert into FTS5 index and Vector Store.
        """
        truth_content = self._extract_truth(full_markdown)
        publish_status = self._resolve_publish_status(full_markdown)

        def sync_upsert() -> None:
            indexed_truth = build_cjk_index_segment(f"{concept_name} {truth_content}")
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM wiki_fts WHERE concept_name = ?", (concept_name,)
                )
                conn.execute(
                    "DELETE FROM wiki_fts WHERE concept_name = ?",
                    (f"raw:{concept_name}",),
                )
                conn.execute(
                    "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                    (concept_name, indexed_truth),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO wiki_index_meta (concept_name, publish_status) VALUES (?, ?)",
                    (concept_name, publish_status),
                )

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
                logger.warning(
                    f"Vector upsert failed for wiki concept '{concept_name}', keeping FTS only: {e}"
                )

    async def delete(self, concept_name: str) -> None:
        """
        Delete concept from FTS5 index, Edges, and Vector Store.
        """

        # 1. Delete from SQLite FTS5 and edges (Sync wrapped in async thread)
        def sync_delete() -> None:
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM wiki_fts WHERE concept_name = ?", (concept_name,)
                )
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
                logger.error(
                    f"Failed to delete vector for wiki concept '{concept_name}': {e}"
                )

    async def search(
        self, query: str, limit: int = 5, offset: int = 0
    ) -> list[tuple[str, float]]:
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
                    attached_dbs = {
                        str(row["name"])
                        for row in conn.execute("PRAGMA database_list").fetchall()
                    }
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
                            decay = (
                                0.9 if str(row["src_tbl"]).startswith("pub_") else 1.0
                            )
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
                                decay = (
                                    0.9
                                    if str(row["src_tbl"]).startswith("pub_")
                                    else 1.0
                                )
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
                    candidate = str(
                        res.document.metadata.get("concept_name", res.document.id)
                    )
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
                final_results = rrf_fusion(
                    [fts_results, vec_results], k=getattr(self._config, "rrf_k", 60)
                )
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
            attached_dbs = {
                str(row["name"])
                for row in conn.execute("PRAGMA database_list").fetchall()
            }
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

            fts_union = " UNION ALL ".join(
                f"SELECT truth_content FROM {t} WHERE concept_name = ?"
                for t in fts_tables
            )
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
        truth_match = re.search(
            r"(## Compiled Truth\n.*?)(?=\n## |$)", content, re.DOTALL
        )
        if truth_match:
            truth_content += truth_match.group(1).strip()
        else:
            # Fallback
            truth_content = content

        return truth_content
