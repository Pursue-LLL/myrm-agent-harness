# [INPUT]: BatchSearchReceipt, DualStrategyRrfRetriever, EphemeralFts5Config, SearchQueryItem, SearchResultChunk
# [OUTPUT]: BatchQueriesCoalescingGate
# [POS]: agent/context_management/ephemeral_fts5/batch_queries_coalescing_gate.py

"""Batch queries coalescing gate executing all session lookups in a single round.

[INPUT]
- BatchSearchReceipt, EphemeralFts5Config, SearchQueryItem, SearchResultChunk: Domain definitions.
- DualStrategyRrfRetriever: Matcher engine.

[OUTPUT]
- BatchQueriesCoalescingGate: Gate enforcing batched query dispatch and structured rendering.

[POS]
Query dispatch coalescing and context formatting layer for ephemeral session FTS5 vault.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence

from .dual_strategy_rrf_retriever import DualStrategyRrfRetriever
from .ephemeral_fts5_types import (
    BatchSearchReceipt,
    EphemeralFts5Config,
    SearchQueryItem,
    SearchResultChunk,
)


class BatchQueriesCoalescingGate:
    """Enforces single-turn batching across multiple search queries and formats unified context."""

    def __init__(
        self,
        retriever: DualStrategyRrfRetriever,
        config: EphemeralFts5Config | None = None,
    ) -> None:
        self._retriever = retriever
        self._config = config or EphemeralFts5Config()

    def execute_batch(
        self,
        session_id: str,
        queries: Sequence[str | SearchQueryItem],
        default_top_k: int = 4,
    ) -> BatchSearchReceipt:
        """Executes all requested queries in one round and produces a consolidated result receipt."""
        start_time = time.perf_counter()

        # 1. Normalize and deduplicate queries
        normalized_queries: list[SearchQueryItem] = []
        seen_texts: set[str] = set()

        for q in queries:
            if isinstance(q, SearchQueryItem):
                item = q
            else:
                item = SearchQueryItem(query_text=str(q).strip(), top_k=default_top_k)

            text_key = item.query_text.lower().strip()
            if text_key and text_key not in seen_texts:
                seen_texts.add(text_key)
                normalized_queries.append(item)

        results_by_query: dict[str, Sequence[SearchResultChunk]] = {}
        total_chunks = 0

        # 2. Sequential execution across normalized queries
        for item in normalized_queries:
            chunks = self._retriever.search(item)
            results_by_query[item.query_text] = chunks
            total_chunks += len(chunks)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # 3. Render structured context block
        rendered = self._render_batch_context_block(results_by_query)

        return BatchSearchReceipt(
            session_id=session_id,
            results_by_query=results_by_query,
            total_queries=len(normalized_queries),
            total_results_returned=total_chunks,
            execution_duration_ms=round(duration_ms, 2),
            rendered_context_block=rendered,
        )

    def _render_batch_context_block(
        self,
        results_by_query: Mapping[str, Sequence[SearchResultChunk]],
    ) -> str:
        """Renders model-readable consolidated evidence block for prompt consumption."""
        if not results_by_query:
            return "<session_search_results>\nNo matching content found.\n</session_search_results>"

        lines: list[str] = ["<session_search_results>"]

        for query_text, chunks in results_by_query.items():
            lines.append(f'  <query text="{query_text}" results="{len(chunks)}">')
            if not chunks:
                lines.append("    (No matching chunks)")
            else:
                for idx, ch in enumerate(chunks, 1):
                    code_flag = " [CODE]" if ch.has_code_block else ""
                    lines.append(
                        f'    <result index="{idx}" doc="{ch.document_id}" heading="{ch.heading_path}" score="{ch.rrf_score}"{code_flag}>'
                    )
                    # Indent chunk content
                    for content_line in ch.content.splitlines():
                        lines.append(f"      {content_line}")
                    lines.append("    </result>")
            lines.append("  </query>")

        lines.append("</session_search_results>")
        return "\n".join(lines)
