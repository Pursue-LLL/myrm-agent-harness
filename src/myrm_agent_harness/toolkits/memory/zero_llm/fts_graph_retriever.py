"""Zero-LLM FTS5 and topological entity graph retriever.

Performs lexical full-text indexing queries combined with 1-hop [[Wikilink]]
graph traversal directly against SQLite FTS5 virtual tables.
Consumes zero LLM tokens and yields sub-millisecond retrieval latency.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from myrm_agent_harness.toolkits.memory.zero_llm.types import (
    FtsGraphSearchHit,
    ZeroLlmSearchResult,
)

_RE_WIKILINK = re.compile(r"\[\[([^\[\]|\n]+?)(?:\|([^\[\]\n]+?))?\]\]")


class ZeroLlmFtsGraphRetriever:
    """Executes FTS5 lexical matching and wikilink graph neighbor expansion."""

    def __init__(
        self,
        db_path: Path | str,
        limit: int = 10,
        graph_hop_decay: float = 0.5,
    ) -> None:
        self.db_path = Path(db_path)
        self.limit = limit
        self.graph_hop_decay = graph_hop_decay

    def search(self, query: str, profile_id: str | None = None) -> ZeroLlmSearchResult:
        """Search across FTS5 virtual table and traverse 1-hop wikilink graph neighbors."""
        clean_query = query.strip()
        if not clean_query:
            return ZeroLlmSearchResult(query=clean_query, hits=[], total_hits=0)

        if not self.db_path.exists():
            return ZeroLlmSearchResult(query=clean_query, hits=[], total_hits=0)

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            primary_hits = self._query_fts5(conn, clean_query, profile_id)
            expanded_hits = self._expand_graph_neighbors(conn, primary_hits, profile_id)
            # Sort descending by composite score
            expanded_hits.sort(key=lambda h: h.composite_score, reverse=True)
            final_hits = expanded_hits[: self.limit]
            return ZeroLlmSearchResult(
                query=clean_query,
                hits=final_hits,
                total_hits=len(expanded_hits),
                zero_token_cost=True,
            )
        finally:
            conn.close()

    def _query_fts5(
        self,
        conn: sqlite3.Connection,
        query: str,
        profile_id: str | None,
    ) -> list[FtsGraphSearchHit]:
        """Query direct lexical hits using FTS5 match."""
        # Sanitize query for FTS5 syntax
        fts_query = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', query).strip()
        tokens = [t for t in fts_query.split() if len(t) > 0]
        if not tokens:
            return []

        fts_match_expr = " OR ".join(f'"{t}"*' for t in tokens)

        sql = """
            SELECT
                p.page_slug,
                p.title,
                p.content,
                rank as bm25_score
            FROM wiki_pages_fts
            JOIN wiki_pages p ON wiki_pages_fts.rowid = p.id
            WHERE wiki_pages_fts MATCH ?
        """
        params: list[str] = [fts_match_expr]
        if profile_id:
            sql += " AND (p.scope_level = 'global' OR p.agent_profile_id = ?)"
            params.append(profile_id)

        sql += f" ORDER BY rank LIMIT {self.limit}"

        hits: list[FtsGraphSearchHit] = []
        try:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            for r in rows:
                slug = str(r["page_slug"])
                title = str(r["title"])
                content = str(r["content"])
                raw_rank = float(r["bm25_score"])
                # FTS5 rank is typically negative; convert to positive normalized score
                normalized_score = max(0.1, 10.0 / (1.0 + abs(raw_rank)))
                entities = self._extract_entities(content)
                snippet = content[:180].replace("\n", " ").strip()
                hits.append(
                    FtsGraphSearchHit(
                        page_slug=slug,
                        title=title,
                        snippet=snippet,
                        fts_score=normalized_score,
                        graph_hops=0,
                        composite_score=normalized_score,
                        linked_entities=entities,
                    )
                )
        except sqlite3.OperationalError:
            # Table might not exist or empty FTS
            return []

        return hits

    def _expand_graph_neighbors(
        self,
        conn: sqlite3.Connection,
        primary_hits: Sequence[FtsGraphSearchHit],
        profile_id: str | None,
    ) -> list[FtsGraphSearchHit]:
        """Traverse 1-hop Wikilink relations to enrich context without LLM inference."""
        all_hits: dict[str, FtsGraphSearchHit] = {h.page_slug: h for h in primary_hits}
        target_entities: set[str] = set()

        for hit in primary_hits:
            for ent in hit.linked_entities:
                if ent not in all_hits:
                    target_entities.add(ent)

        if not target_entities:
            return list(all_hits.values())

        # Resolve entity target pages
        placeholders = ",".join("?" for _ in target_entities)
        sql = f"""
            SELECT page_slug, title, content
            FROM wiki_pages
            WHERE title IN ({placeholders}) OR page_slug IN ({placeholders})
        """
        params = list(target_entities) + list(target_entities)
        if profile_id:
            sql += " AND (scope_level = 'global' OR agent_profile_id = ?)"
            params.append(profile_id)

        try:
            cursor = conn.execute(sql, params)
            for r in cursor.fetchall():
                slug = str(r["page_slug"])
                if slug in all_hits:
                    continue
                title = str(r["title"])
                content = str(r["content"])
                # Calculate decayed composite score
                parent_score = max((h.composite_score for h in primary_hits), default=1.0)
                decayed_score = parent_score * self.graph_hop_decay
                snippet = content[:180].replace("\n", " ").strip()
                all_hits[slug] = FtsGraphSearchHit(
                    page_slug=slug,
                    title=title,
                    snippet=snippet,
                    fts_score=0.0,
                    graph_hops=1,
                    composite_score=decayed_score,
                    linked_entities=self._extract_entities(content),
                )
        except sqlite3.OperationalError:
            pass

        return list(all_hits.values())

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Extract explicit [[Wikilink]] target identifiers from markdown text."""
        targets: list[str] = []
        for m in _RE_WIKILINK.finditer(text):
            target = m.group(1).strip()
            if target and target not in targets:
                targets.append(target)
        return targets
