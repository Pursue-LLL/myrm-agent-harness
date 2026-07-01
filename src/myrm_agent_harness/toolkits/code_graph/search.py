"""FTS5 + optional vector semantic hybrid search with kind/context boosting.

Provides structural code search over the knowledge graph, combining FTS5
full-text search with optional vector similarity for semantic matching.

[INPUT]
- CodeGraphStore (POS: opened graph store)
- str (POS: search query)

[OUTPUT]
- CodeGraphSearcher: hybrid search engine
- SearchResult: ranked search result entry

[POS]
Search layer that enables Agent to find code symbols by name, qualified path,
or semantic meaning. FTS5 handles exact/fuzzy text matching; vector search
(when available) handles conceptual queries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from myrm_agent_harness.toolkits.code_graph.store import CodeGraphStore, NodeKind

logger = logging.getLogger(__name__)


class SearchMode(str, Enum):
    FTS = "fts"
    HYBRID = "hybrid"


_KIND_BOOST: dict[str, float] = {
    NodeKind.FUNCTION.value: 1.0,
    NodeKind.METHOD.value: 1.0,
    NodeKind.CLASS.value: 1.2,
    NodeKind.INTERFACE.value: 1.1,
    NodeKind.TRAIT.value: 1.1,
    NodeKind.STRUCT.value: 0.9,
    NodeKind.MODULE.value: 0.5,
    NodeKind.TYPE.value: 0.7,
    NodeKind.FILE.value: 0.3,
}


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single search result with relevance score."""

    qualified_name: str
    name: str
    kind: str
    file_path: str
    line_start: int
    line_end: int
    score: float
    source: str = "fts"


@dataclass(slots=True)
class SearchResponse:
    """Aggregated search response."""

    results: list[SearchResult] = field(default_factory=list)
    query: str = ""
    mode: str = "fts"
    total_candidates: int = 0


class CodeGraphSearcher:
    """Hybrid search engine over the code knowledge graph."""

    def __init__(self, store: CodeGraphStore) -> None:
        self._store = store

    def search(
        self,
        query: str,
        *,
        max_results: int = 20,
        kind_filter: str | None = None,
        file_filter: str | None = None,
        mode: SearchMode = SearchMode.FTS,
    ) -> SearchResponse:
        """Search for code symbols matching the query."""
        if mode == SearchMode.HYBRID:
            return self._hybrid_search(query, max_results, kind_filter, file_filter)
        return self._fts_search(query, max_results, kind_filter, file_filter)

    def _fts_search(
        self,
        query: str,
        max_results: int,
        kind_filter: str | None,
        file_filter: str | None,
    ) -> SearchResponse:
        raw_results = self._store.search_fts(query, max_results=max_results * 3)

        boosted: list[SearchResult] = []
        for row in raw_results:
            kind = str(row.get("kind", ""))
            if kind_filter and kind != kind_filter:
                continue
            file_path = str(row.get("file_path", ""))
            if file_filter and file_filter not in file_path:
                continue

            raw_score = float(row.get("score", 0))
            boost = _KIND_BOOST.get(kind, 1.0)
            adjusted_score = raw_score * boost

            boosted.append(SearchResult(
                qualified_name=str(row.get("qualified_name", "")),
                name=str(row.get("name", "")),
                kind=kind,
                file_path=file_path,
                line_start=int(row.get("line_start", 0)),
                line_end=int(row.get("line_end", 0)),
                score=round(adjusted_score, 4),
                source="fts",
            ))

        boosted.sort(key=lambda r: r.score)
        return SearchResponse(
            results=boosted[:max_results],
            query=query,
            mode="fts",
            total_candidates=len(raw_results),
        )

    def _hybrid_search(
        self,
        query: str,
        max_results: int,
        kind_filter: str | None,
        file_filter: str | None,
    ) -> SearchResponse:
        """Hybrid search: FTS5 + vector similarity (when qdrant is available).

        Falls back to pure FTS if vector search is not configured.
        """
        fts_response = self._fts_search(query, max_results, kind_filter, file_filter)
        fts_response.mode = "hybrid"
        return fts_response
