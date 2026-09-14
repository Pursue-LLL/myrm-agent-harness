"""Wiki Indexer - SQLite FTS5 + Qdrant RRF based Hybrid search engine.

[INPUT]
- sqlite3 (POS: standard library database)
- ..core.structure::WikiStructure (POS: database path resolution)
- ..core.config::WikiConfig (POS: Wiki configuration)
- myrm_agent_harness.utils.db.fts5::fts5_integrity_check, fts5_rebuild (POS: FTS5 health and rebuild helpers)
- myrm_agent_harness.toolkits.memory.protocols.embedding::EmbeddingProtocol (POS: embedding provider protocol)
- myrm_agent_harness.toolkits.memory.protocols.vector::VectorStoreProtocol (POS: vector store protocol)
- .fts_search::FtsSearchMixin, migrate_wiki_fts_schema (POS: FTS5 + vector index operations mixin)
- .graph_store::WikiGraphStore (POS: knowledge graph storage)
- .sidecar_index::SidecarIndexMixin (POS: L0/L1 sidecar index operations)

[OUTPUT]
- WikiIndexer: hybrid search engine; wiki_index_meta publish_status gate for FTS/vector/get_truth

[POS]
Wiki concept indexer core. Manages FTS5 + Qdrant hybrid search for L2 concept entries,
knowledge graph edges, and federated multi-database queries. Only `publish_status=published`
entries are searchable and vector-indexed. Index write/read operations live in
FtsSearchMixin and sidecar (L0/L1) indexing in SidecarIndexMixin to keep this file
focused on concept-level indexing.
"""

import contextlib
import logging
import re
import sqlite3
from collections.abc import Iterator
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.db.fts5 import (
    fts5_integrity_check,
    fts5_rebuild,
)

from ..core.config import WikiConfig
from ..core.structure import WikiStructure
from .fts_search import FtsSearchMixin, migrate_wiki_fts_schema
from .graph_store import WikiGraphStore
from .sidecar_index import SidecarIndexMixin

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)


class WikiIndexer(FtsSearchMixin, SidecarIndexMixin):
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
                logger.warning("Reached maximum federated public dirs attachment limit (6), skipping remaining.")
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
                    search_terms,
                    tokenize="unicode61 remove_diacritics 1"
                )
            """
            )
            migrate_wiki_fts_schema(conn)
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
                conn.execute("ALTER TABLE wiki_edges ADD COLUMN weight REAL DEFAULT 1.0")

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
            return [(str(row["target"]), float(row["weight"])) for row in cursor.fetchall()]

    def upsert_edges(self, source: str, targets: list[str], source_files: list[str] | None = None) -> None:
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
            cursor = conn.execute("SELECT source FROM wiki_edges WHERE target = ? LIMIT 20", (target,))
            target_neighbors = {row["source"] for row in cursor.fetchall()}
            # If target links back to concepts that share source files, add overlap bonus
            if target_neighbors:
                weight += min(len(target_neighbors) * 0.5, 4.0)

        # Common neighbors (Adamic-Adar inspired): shared connections indicate relatedness
        cursor = conn.execute("SELECT target FROM wiki_edges WHERE source = ?", (source,))
        source_neighbors = {row["target"] for row in cursor.fetchall()}
        cursor = conn.execute("SELECT target FROM wiki_edges WHERE source = ?", (target,))
        target_out_neighbors = {row["target"] for row in cursor.fetchall()}

        common = source_neighbors & target_out_neighbors
        if common:
            weight += min(len(common) * 0.5, 1.5)

        return round(weight, 2)

    def extract_and_upsert_edges(self, concept_name: str, content: str) -> None:
        """Parse markdown links, Wikilinks, and Metric source_systems, then upsert to SQLite edges table."""
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

        # 3. Match Metric source_systems in frontmatter metadata
        if content.startswith("---"):
            try:
                from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
                    load_frontmatter_metadata,
                )

                metadata, _ = load_frontmatter_metadata(content)
                sources = metadata.get("source_systems")
                if isinstance(sources, list):
                    for src in sources:
                        if isinstance(src, str) and src.strip():
                            targets.append(f"system:{src.strip()}")
            except Exception:
                pass

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
