"""Wiki Indexer - SQLite FTS5 + Qdrant RRF based Hybrid search engine.

[INPUT]
sqlite3 (POS: standard library database)
re (POS: standard library regex)
..core.structure::WikiStructure (POS: database path resolution)
..core.config::WikiConfig (POS: Wiki configuration)
myrm_agent_harness.toolkits.vector.base::VectorDocument (POS: vector document)
myrm_agent_harness.toolkits.retriever.fusion_strategies::rrf_fusion (POS: result fusion strategy)

[OUTPUT]
WikiIndexer: high-performance hybrid search engine based on FTS5 + Qdrant

[POS]
Solves the critical blocking issue of dynamic full-file BM25 scanning on every query,
while improving semantic understanding through hybrid retrieval.
Only indexes `Compiled Truth`, discards `Timeline`, greatly protecting Agent cache.
"""

import asyncio
import contextlib
import logging
import re
import sqlite3
import uuid
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.toolkits.vector.base import VectorDocument
from myrm_agent_harness.utils.db.fts5 import fts5_auto_heal, fts5_integrity_check, fts5_rebuild

from ..core.config import WikiConfig
from ..core.structure import WikiStructure
from .graph_analysis import compute_graph_insights, enrich_graph_with_communities

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "such",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "will",
        "with",
        "what",
        "how",
        "why",
        "who",
        "where",
        "when",
        "does",
        "do",
        "did",
        "can",
        "could",
        "should",
        "would",
        "的",
        "了",
        "和",
        "是",
        "就",
        "都",
        "而",
        "及",
        "与",
        "着",
        "或",
        "一个",
        "没有",
        "我们",
        "你们",
        "他们",
        "它",
        "它们",
        "什么",
        "怎么",
        "如何",
        "为什么",
        "谁",
        "在哪",
        "何时",
    }
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uF900-\uFAFF]+")


def _tokenize_for_fts(query: str) -> str:
    """Build FTS5 query with CJK bigram support for proper Chinese/Japanese/Korean search."""
    tokens: list[str] = []

    # Extract CJK segments and create bigrams
    cjk_segments = _CJK_RE.findall(query)
    for seg in cjk_segments:
        if len(seg) == 1:
            tokens.append(f'"{seg}"')
        else:
            for i in range(len(seg) - 1):
                tokens.append(f'"{seg[i]}{seg[i + 1]}"')

    # Extract non-CJK Latin words
    latin_text = _CJK_RE.sub(" ", query)
    for word in latin_text.split():
        if word.lower() not in _STOP_WORDS and word.strip():
            tokens.append(f'"{word}"')

    return " ".join(tokens)


class WikiIndexer:
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

    @contextlib.contextmanager
    def _get_conn(self):
        from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, CACHE, db_path=self.db_path)

        # Dynamically ATTACH federated public databases (Read-Only)
        for idx, p_dir in enumerate(self._structure.public_dirs):
            pub_db = p_dir / ".wiki_index.db"
            if pub_db.exists():
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(f"ATTACH DATABASE ? AS pub_{idx}", (str(pub_db),))

        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            # Use FTS5 for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
                    concept_name,
                    truth_content,
                    tokenize="unicode61 remove_diacritics 1"
                )
            """)
            # 增量 O(1) 图谱双链关系表 (Holographic Graph Persistence)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wiki_edges(
                    source TEXT,
                    target TEXT,
                    weight REAL DEFAULT 1.0,
                    PRIMARY KEY (source, target)
                )
            """)
            # Migrate: add weight column to existing tables created before this version
            # (OperationalError means the column already exists).
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE wiki_edges ADD COLUMN weight REAL DEFAULT 1.0")

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_wiki_edges_target ON wiki_edges(target)
            """)

            if not fts5_integrity_check(conn, "wiki_fts"):
                logger.warning("FTS5 index corrupted on startup, rebuilding: wiki_fts")
                fts5_rebuild(conn, "wiki_fts")

    def get_knowledge_graph(self, center_node: str | None = None, depth: int = 1, limit: int = 1000) -> dict[str, list]:
        """Fetch the full topology graph in O(1) DB read time, with progressive BFS support across federated databases."""
        nodes = []
        edges = []
        node_ids = set()

        with self._get_conn() as conn:
            # Build federated UNION queries
            fts_tables = ["wiki_fts"]
            edges_tables = ["wiki_edges"]
            for idx, p_dir in enumerate(self._structure.public_dirs):
                if (p_dir / ".wiki_index.db").exists():
                    fts_tables.append(f"pub_{idx}.wiki_fts")
                    edges_tables.append(f"pub_{idx}.wiki_edges")

            fts_union = " UNION ALL ".join(f"SELECT concept_name FROM {t}" for t in fts_tables)
            edges_union = " UNION ALL ".join(f"SELECT source, target, weight FROM {t}" for t in edges_tables)

            if not center_node:
                # Global fetch with hard limit to prevent OOM
                cursor = conn.execute(f"SELECT concept_name FROM ({fts_union}) LIMIT ?", (limit,))
                for row in cursor.fetchall():
                    node_id = row["concept_name"]
                    nodes.append({"id": node_id, "name": node_id.replace("-", " "), "group": 1})
                    node_ids.add(node_id)

                if node_ids:
                    cursor = conn.execute(f"SELECT source, target, weight FROM ({edges_union})")
                    for row in cursor.fetchall():
                        src = row["source"]
                        tgt = row["target"]
                        if src in node_ids and tgt in node_ids:
                            edges.append({"source": src, "target": tgt, "weight": row["weight"] or 1.0})
            else:
                # BFS starting from center_node
                current_level = {center_node}
                visited_nodes = {center_node}
                all_edges = []

                # Check if center node exists
                cursor = conn.execute(f"SELECT concept_name FROM ({fts_union}) WHERE concept_name = ?", (center_node,))
                if cursor.fetchone():
                    nodes.append({"id": center_node, "name": center_node.replace("-", " "), "group": 1})

                for _ in range(depth):
                    if not current_level:
                        break
                    next_level = set()

                    placeholders = ",".join(["?"] * len(current_level))
                    params = tuple(current_level)

                    # Outgoing edges
                    cursor = conn.execute(
                        f"SELECT source, target, weight FROM ({edges_union}) WHERE source IN ({placeholders})", params
                    )
                    for row in cursor.fetchall():
                        src, tgt = row["source"], row["target"]
                        all_edges.append({"source": src, "target": tgt, "weight": row["weight"] or 1.0})
                        if tgt not in visited_nodes:
                            next_level.add(tgt)

                    # Incoming edges (Fast due to idx_wiki_edges_target)
                    cursor = conn.execute(
                        f"SELECT source, target, weight FROM ({edges_union}) WHERE target IN ({placeholders})", params
                    )
                    for row in cursor.fetchall():
                        src, tgt = row["source"], row["target"]
                        all_edges.append({"source": src, "target": tgt, "weight": row["weight"] or 1.0})
                        if src not in visited_nodes:
                            next_level.add(src)

                    # Fetch nodes info for next_level
                    if next_level:
                        np_placeholders = ",".join(["?"] * len(next_level))
                        np_params = tuple(next_level)
                        cursor = conn.execute(
                            f"SELECT concept_name FROM ({fts_union}) WHERE concept_name IN ({np_placeholders})",
                            np_params,
                        )
                        for row in cursor.fetchall():
                            nid = row["concept_name"]
                            if nid not in visited_nodes:
                                nodes.append({"id": nid, "name": nid.replace("-", " "), "group": 1})
                                visited_nodes.add(nid)

                    current_level = next_level
                    if len(visited_nodes) >= limit:
                        break

                # Dedup edges
                unique_edges = {}
                for e in all_edges:
                    if e["source"] in visited_nodes and e["target"] in visited_nodes:
                        unique_edges[(e["source"], e["target"])] = e
                edges = list(unique_edges.values())

        enrich_graph_with_communities(nodes, edges)

        return {"nodes": nodes, "edges": edges}

    def graph_insights(self) -> dict[str, list[dict]]:
        """Analyze graph structure for unexpected connections, knowledge gaps, and communities."""
        with self._get_conn() as conn:
            return compute_graph_insights(conn)

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
        self, conn: sqlite3.Connection, source: str, target: str, source_files: list[str] | None
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

    def _concept_to_uuid(self, concept_name: str) -> str:
        """Convert concept name to a deterministic UUID for Qdrant."""
        return str(uuid.uuid5(uuid.NAMESPACE_OID, concept_name))

    def index_raw_text(self, name: str, text: str) -> None:
        """Index raw text into FTS5 for immediate searchability before compilation.

        Uses a ``raw:`` prefix to distinguish from compiled entries. When the
        compiled version is later upserted via :meth:`upsert`, it replaces
        this interim entry.
        """
        raw_key = f"raw:{name}"
        preview = text[:5000] if len(text) > 5000 else text

        with self._get_conn() as conn:
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (raw_key,))
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                (raw_key, preview),
            )

    async def upsert(self, concept_name: str, full_markdown: str) -> None:
        """
        Extract Compiled Truth and upsert into FTS5 index and Vector Store.
        """
        truth_content = self._extract_truth(full_markdown)

        def sync_upsert():
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (concept_name,))
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (f"raw:{concept_name}",))
                conn.execute(
                    "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)", (concept_name, truth_content)
                )

        await asyncio.to_thread(sync_upsert)

        # 2. Upsert to Vector Store (Async)
        if self._config.enable_hybrid_search and self._vector and self._embedding:
            await self._ensure_collection()
            try:
                vec = await self._embedding.embed(truth_content)
                doc_id = self._concept_to_uuid(concept_name)
                doc = VectorDocument(
                    id=doc_id,
                    content=truth_content,
                    vector=vec,
                    metadata={"concept_name": concept_name},
                )
                await self._vector.upsert(self._collection_name, [doc])
            except Exception as e:
                logger.error(f"Failed to upsert vector for wiki concept '{concept_name}': {e}")

    async def delete(self, concept_name: str) -> None:
        """
        Delete concept from FTS5 index, Edges, and Vector Store.
        """

        # 1. Delete from SQLite FTS5 and edges (Sync wrapped in async thread)
        def sync_delete():
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (concept_name,))
                conn.execute("DELETE FROM wiki_edges WHERE source = ? OR target = ?", (concept_name, concept_name))

        await asyncio.to_thread(sync_delete)

        # 2. Delete from Vector Store (Async)
        if self._config.enable_hybrid_search and self._vector:
            doc_id = self._concept_to_uuid(concept_name)
            try:
                # Assuming VectorStoreProtocol has a delete method.
                # If not, some implement delete by providing empty vectors or it might crash.
                # We should check if _vector has delete.
                if hasattr(self._vector, "delete"):
                    await self._vector.delete(self._collection_name, [doc_id])
                else:
                    logger.warning("Vector store does not support deletion.")
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

        def sync_fts_search():
            results = []
            with self._get_conn() as conn:
                try:
                    fts_tables = ["wiki_fts"]
                    for idx, p_dir in enumerate(self._structure.public_dirs):
                        if (p_dir / ".wiki_index.db").exists():
                            fts_tables.append(f"pub_{idx}.wiki_fts")

                    fts_query = _tokenize_for_fts(safe_query)

                    if fts_query:
                        # In SQLite FTS5, the MATCH operator can be used on the table name.
                        # e.g., pub_0.wiki_fts MATCH ? is valid, but the column name inside WHERE is wiki_fts MATCH ?
                        fts_union = " UNION ALL ".join(
                            f"SELECT concept_name, rank FROM {t} WHERE {t.split('.')[-1]} MATCH ?" for t in fts_tables
                        )
                        params = (fts_query,) * len(fts_tables)

                        cursor = conn.execute(
                            f"""
                            SELECT concept_name, rank
                            FROM ({fts_union})
                            ORDER BY rank
                            LIMIT ? OFFSET ?
                            """,
                            (*params, limit * 2, offset),  # Fetch more for fusion
                        )

                        for row in cursor.fetchall():
                            # FTS5 rank is negative, lower is better. We invert it for RRF fusion.
                            score = 1.0 / (abs(row["rank"]) + 1.0)
                            results.append((row["concept_name"], score))
                except sqlite3.OperationalError as e:
                    logger.error(f"FTS search error: {e}")
                    healed = fts5_auto_heal(conn, "wiki_fts")
                    if healed and fts_query:
                        logger.info("FTS5 auto-heal succeeded, retrying search")
                        with contextlib.suppress(sqlite3.OperationalError):
                            cursor = conn.execute(
                                f"""
                                SELECT concept_name, rank
                                FROM ({fts_union})
                                ORDER BY rank
                                LIMIT ? OFFSET ?
                                """,
                                (*params, limit * 2, offset),
                            )
                            for row in cursor.fetchall():
                                score = 1.0 / (abs(row["rank"]) + 1.0)
                                results.append((row["concept_name"], score))
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
                    vec_results.append((res.document.metadata.get("concept_name", res.document.id), res.score))
            except Exception as e:
                logger.error(f"Wiki vector search failed: {e}")

        # 3. Hybrid Fusion (RRF)
        if self._config.enable_hybrid_search and self._vector and self._embedding:
            if fts_results or vec_results:
                fused = rrf_fusion([fts_results, vec_results], k=getattr(self._config, "rrf_k", 60))
                final_results = [(doc_id, score) for doc_id, score in fused]
            else:
                final_results = []
        else:
            final_results = fts_results

        # Sort and truncate
        final_results.sort(key=lambda x: x[1], reverse=True)
        return final_results[:limit]

    def get_truth(self, concept_name: str) -> str | None:
        """Get the cached truth content for context injection."""
        with self._get_conn() as conn:
            fts_tables = ["wiki_fts"]
            for idx, p_dir in enumerate(self._structure.public_dirs):
                if (p_dir / ".wiki_index.db").exists():
                    fts_tables.append(f"pub_{idx}.wiki_fts")

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
