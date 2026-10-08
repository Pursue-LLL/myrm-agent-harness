# [INPUT]: None
# [OUTPUT]: BatchSearchReceipt, DocumentChunk, EphemeralFts5Config, IndexReceipt, SearchQueryItem, SearchResultChunk
# [POS]: agent/context_management/ephemeral_fts5/ephemeral_fts5_types.py

"""Domain models and contracts for ephemeral session-isolated SQLite FTS5 indexing and batch retrieval.

[INPUT]
- None (Self-contained domain models for temporary session knowledge vaults).

[OUTPUT]
- DocumentChunk: Individual indexable text slice preserving heading hierarchy and code block fences.
- IndexReceipt: Metadata result returned upon indexing a document.
- SearchQueryItem: Specific query instruction within a batched request.
- SearchResultChunk: Scored search result item with source document and snippet context.
- BatchSearchReceipt: Unified response containing results for all queries in a single round.
- EphemeralFts5Config: Configuration controlling chunk limits, RRF smoothing constants, and storage path.

[POS]
Domain contract layer for ephemeral FTS5 session indexing in context management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class DocumentChunk:
    """Atomic text chunk extracted from markdown or source document."""

    chunk_id: str
    document_id: str
    session_id: str
    heading_path: str
    content: str
    has_code_block: bool
    char_count: int
    token_estimate: int
    content_hash: str


@dataclass(frozen=True)
class IndexReceipt:
    """Outcome receipt of indexing a document into the ephemeral FTS5 vault."""

    session_id: str
    document_id: str
    total_chunks: int
    total_chars: int
    total_tokens_estimated: int
    db_path: str
    status: str = "success"


@dataclass(frozen=True)
class SearchQueryItem:
    """Individual query term inside a batched query request."""

    query_text: str
    top_k: int = 5
    boost_code_blocks: bool = True


@dataclass(frozen=True)
class SearchResultChunk:
    """Single matched chunk enriched with BM25 rank, strategy scores, and RRF fused score."""

    chunk_id: str
    document_id: str
    heading_path: str
    content: str
    has_code_block: bool
    porter_rank: int | None
    trigram_rank: int | None
    rrf_score: float
    token_estimate: int


@dataclass(frozen=True)
class BatchSearchReceipt:
    """Aggregated output containing ranked results grouped by each requested query."""

    session_id: str
    results_by_query: Mapping[str, Sequence[SearchResultChunk]]
    total_queries: int
    total_results_returned: int
    execution_duration_ms: float
    rendered_context_block: str


@dataclass(frozen=True)
class EphemeralFts5Config:
    """Settings controlling storage isolation, chunking, and ranking algorithms."""

    db_path_template: str = ":memory:"
    max_chunk_chars: int = 1600
    min_chunk_chars: int = 80
    rrf_k_constant: int = 60
    code_block_weight: float = 1.25
    enforce_batch_queries: bool = True
