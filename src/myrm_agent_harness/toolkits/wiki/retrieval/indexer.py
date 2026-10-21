"""Wiki Indexer - SQLite FTS5 + Qdrant RRF based Hybrid search engine.

[INPUT]
- sqlite3 (POS: standard library database)
- ..core.structure::WikiStructure (POS: database path resolution)
- ..core.config::WikiConfig (POS: Wiki configuration)
- ..core.link_extraction::extract_markdown_link_targets, extract_wikilink_targets (POS: link syntax SSOT; code regions are never links)
- ..core.link_resolver::WikiLinkResolver, concept_index_key, concept_page_exists (POS: link target resolution and page-key identity SSOT)
- myrm_agent_harness.utils.db.fts5::fts5_integrity_check, fts5_rebuild (POS: FTS5 health and rebuild helpers)
- myrm_agent_harness.toolkits.memory.protocols.embedding::EmbeddingProtocol (POS: embedding provider protocol)
- myrm_agent_harness.toolkits.memory.protocols.vector::VectorStoreProtocol (POS: vector store protocol)
- .fts_search::FtsSearchMixin, migrate_wiki_fts_schema (POS: FTS5 + vector search and truth lookup mixin)
- .fts_write::FtsWriteMixin (POS: FTS5 + vector upsert/delete mixin)
- .concept_links::ConceptLinks (POS: typed concept link lookup result)
- .edge_links::canonical_edge_target, linkers_to_reread, relink_dangling_edges, store_edge (POS: edge targets stored as page keys, converged when pages appear or disappear)
- .edge_weights::refresh_edge_weights (POS: edge weights re-derived for the pages whose links changed)
- .graph_store::WikiGraphStore (POS: knowledge graph storage)
- .identity_migration::migrate_index_schema (POS: one-time index migrations: page identity, edge link spellings)
- .sidecar_index::SidecarIndexMixin (POS: L0/L1 sidecar index operations)

[OUTPUT]
- WikiIndexer: hybrid search engine; one index row per page key; wiki_index_meta publish_status gate for FTS/vector/get_truth

[POS]
Wiki concept indexer core. Manages FTS5 + Qdrant hybrid search for L2 concept entries,
knowledge graph edges (targets resolved to page keys, weights derived from the stored edges), and federated multi-database queries. Only `publish_status=published`
entries are searchable and vector-indexed. Index writes live in FtsWriteMixin, reads in
FtsSearchMixin and sidecar (L0/L1) indexing in SidecarIndexMixin to keep this file
focused on concept-level indexing.
"""

import contextlib
import logging
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.db.fts5 import (
    fts5_integrity_check,
    fts5_rebuild,
)

from ..core.config import WikiConfig
from ..core.link_extraction import extract_markdown_link_targets, extract_wikilink_targets
from ..core.link_resolver import WikiLinkResolver, concept_index_key, concept_page_exists
from ..core.structure import WikiStructure
from .concept_links import ConceptLinks
from .edge_links import canonical_edge_target, linkers_to_reread, relink_dangling_edges, store_edge
from .edge_weights import refresh_edge_weights
from .fts_search import FtsSearchMixin, migrate_wiki_fts_schema
from .fts_write import FtsWriteMixin
from .graph_store import WikiGraphStore
from .identity_migration import migrate_index_schema
from .sidecar_index import SidecarIndexMixin

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)


class WikiIndexer(FtsWriteMixin, FtsSearchMixin, SidecarIndexMixin):
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
        self._link_resolver = WikiLinkResolver(structure)
        self._init_db()
        self._graph_store = WikiGraphStore(self._get_conn, structure)

    def _index_key(self, concept_name: str) -> str:
        """Identity a concept is indexed under: its on-disk path when a page exists."""
        return concept_index_key(self._structure, concept_name)

    def _concept_name_variants(self, concept_name: str) -> tuple[str, ...]:
        """Spellings a concept may be indexed under: as given and as its on-disk path."""
        sanitized = WikiStructure._sanitize_path(concept_name.removesuffix(".md"))
        return tuple(dict.fromkeys(name for name in (concept_name, sanitized) if name))

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
                    target_key TEXT,
                    target_slug TEXT,
                    PRIMARY KEY (source, target)
                )
            """
            )
            # Add columns to tables created without them
            # (OperationalError means the column already exists).
            for column in ("weight REAL DEFAULT 1.0", "target_key TEXT", "target_slug TEXT"):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(f"ALTER TABLE wiki_edges ADD COLUMN {column}")

            for column in ("target", "target_key", "target_slug"):
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_wiki_edges_{column} ON wiki_edges({column})")
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

            migrate_index_schema(conn, self._structure, self._link_resolver)

    def get_knowledge_graph(
        self, center_node: str | None = None, depth: int = 1, limit: int = 1000
    ) -> dict[str, list[dict[str, object]]]:
        """Delegate to WikiGraphStore for BFS graph traversal."""
        return self._graph_store.get_knowledge_graph(center_node, depth, limit)

    def graph_insights(self) -> dict[str, list[dict[str, object]]]:
        """Delegate to WikiGraphStore for graph structural analysis."""
        return self._graph_store.graph_insights()

    @property
    def graph_store(self) -> WikiGraphStore:
        """Access underlying WikiGraphStore."""
        return self._graph_store

    def get_concept_links(self, concept_name: str) -> ConceptLinks:
        """Delegate bidirectional links lookup to WikiGraphStore."""
        return self._graph_store.get_concept_links(concept_name)

    def get_outgoing_edges(self, source: str) -> list[tuple[str, float]]:
        """Return weighted outgoing graph edges for a concept, highest weight first, equal weights by name."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT target, weight FROM wiki_edges WHERE source = ? ORDER BY weight DESC, target",
                (source,),
            )
            return [(str(row["target"]), float(row["weight"])) for row in cursor.fetchall()]

    def upsert_edges(self, source: str, targets: list[str]) -> None:
        """Replace the outgoing edges of ``source``; weights follow from the edges now stored."""
        with self._get_conn() as conn:
            self._replace_edges(conn, source, targets)

    def _replace_edges(self, conn: sqlite3.Connection, source: str, targets: Iterable[str]) -> None:
        """Replace ``source``'s edges and re-derive the weight of every edge that starts or ends at it."""
        conn.execute("DELETE FROM wiki_edges WHERE source = ?", (source,))
        for target in targets:
            if source != target:
                store_edge(conn, source, target)
        refresh_edge_weights(conn, (source,))

    def extract_and_upsert_edges(self, concept_name: str, content: str) -> None:
        """Parse markdown links and Wikilinks, then upsert to SQLite edges table.

        `upsert` runs this for every indexed page; call it directly only when a page's links
        changed without its search entry changing (backlink generation).

        Link targets are stored as the canonical key of the page they resolve to, so
        every graph reader sees the links structural lint accepts. When this write adds
        a page or changes its titles/aliases, earlier dangling edges are re-resolved, and
        pages whose links a same-named page makes ambiguous are re-read.
        """
        source = self._index_key(concept_name)
        page_change = (
            self._link_resolver.note_page(source, content) if concept_page_exists(self._structure, source) else None
        )
        linkers: list[str] = []
        # The page's edges and the forward references it resolves land in one transaction.
        with self._get_conn() as conn:
            self._store_page_edges(conn, source, content)
            if page_change is not None:
                relink_dangling_edges(conn, self._link_resolver, page_change)
                linkers = linkers_to_reread(conn, source, page_change, removed=False)
        self._reread_page_links(linkers)

    def _store_page_edges(self, conn: sqlite3.Connection, source: str, content: str) -> None:
        """Replace ``source``'s edges with the links written in ``content``.

        Always replaces, even with nothing, so links that were removed lose their edges.
        """
        resolver = self._link_resolver
        # 1. Markdown links to pages: [text](link.md), [text](link.md#heading)
        page_links = [link[:-3] for link in extract_markdown_link_targets(content) if link.lower().endswith(".md")]
        targets = {
            canonical_edge_target(resolver, source, link, relative_to_source=True)
            for link in page_links
            if link.strip()
        }

        # 2. Obsidian wikilinks: [[link]], [[link|alias]], [[link#heading|alias]]
        targets.update(canonical_edge_target(resolver, source, target) for target in extract_wikilink_targets(content))
        self._replace_edges(conn, source, targets)

    def _reread_page_links(self, sources: Sequence[str]) -> None:
        """Re-resolve the links written in each page of ``sources`` against the pages that exist now.

        A page that disappeared from disk or cannot be read keeps the edges it has.
        """
        pages = {source: content for source in sources if (content := self._read_page(source)) is not None}
        if not pages:
            return
        with self._get_conn() as conn:
            for source, content in pages.items():
                self._store_page_edges(conn, source, content)

    def _read_page(self, key: str) -> str | None:
        if not concept_page_exists(self._structure, key):
            return None
        try:
            return (self._structure.concepts_dir / f"{key}.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Failed to re-read links of wiki page %s: %s", key, exc)
            return None

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
