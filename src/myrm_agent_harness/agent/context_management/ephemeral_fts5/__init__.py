"""Ephemeral session-isolated SQLite FTS5 knowledge vault and batch retrieval package.

[INPUT]
- Internal engine and contract definitions.

[OUTPUT]
- Public module exports for ephemeral session knowledge vaults.

[POS]
Package entry point for ephemeral FTS5 index and batch retrieval suite.
"""

from __future__ import annotations

from .batch_queries_coalescing_gate import BatchQueriesCoalescingGate
from .dual_strategy_rrf_retriever import DualStrategyRrfRetriever
from .ephemeral_fts5_types import (
    BatchSearchReceipt,
    DocumentChunk,
    EphemeralFts5Config,
    IndexReceipt,
    SearchQueryItem,
    SearchResultChunk,
)
from .ephemeral_session_fts5_suite import EphemeralSessionFts5IndexAndBatchRetrieverSuite
from .ephemeral_sqlite_fts5_vault import EphemeralSqliteFts5Vault
from .markdown_code_block_chunker import MarkdownCodeBlockChunker

__all__ = [
    "BatchQueriesCoalescingGate",
    "BatchSearchReceipt",
    "DocumentChunk",
    "DualStrategyRrfRetriever",
    "EphemeralFts5Config",
    "EphemeralSessionFts5IndexAndBatchRetrieverSuite",
    "EphemeralSqliteFts5Vault",
    "IndexReceipt",
    "MarkdownCodeBlockChunker",
    "SearchQueryItem",
    "SearchResultChunk",
]
