"""End-to-end facade orchestrating ephemeral session FTS5 vault indexing and batch retrieval.

[INPUT]
- Domain models: DocumentChunk, IndexReceipt, SearchQueryItem, SearchResultChunk, BatchSearchReceipt, EphemeralFts5Config.
- Component engines: MarkdownCodeBlockChunker, EphemeralSqliteFts5Vault, DualStrategyRrfRetriever, BatchQueriesCoalescingGate.

[OUTPUT]
- EphemeralSessionFts5IndexAndBatchRetrieverSuite: Top-level unified facade.

[POS]
Main entry point in agent/context_management/ephemeral_fts5 providing ephemeral session knowledge tools.
"""

from __future__ import annotations

from typing import Sequence

from .batch_queries_coalescing_gate import BatchQueriesCoalescingGate
from .dual_strategy_rrf_retriever import DualStrategyRrfRetriever
from .ephemeral_fts5_types import (
    BatchSearchReceipt,
    EphemeralFts5Config,
    IndexReceipt,
    SearchQueryItem,
    SearchResultChunk,
)
from .ephemeral_sqlite_fts5_vault import EphemeralSqliteFts5Vault
from .markdown_code_block_chunker import MarkdownCodeBlockChunker


class EphemeralSessionFts5IndexAndBatchRetrieverSuite:
    """Unified facade managing ephemeral session FTS5 chunking, dual-strategy RRF search, and batch coalescing."""

    def __init__(
        self,
        session_id: str,
        config: EphemeralFts5Config | None = None,
        db_path: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._config = config or EphemeralFts5Config()
        self._chunker = MarkdownCodeBlockChunker(self._config)
        self._vault = EphemeralSqliteFts5Vault(
            session_id=session_id,
            config=self._config,
            db_path=db_path,
        )
        self._retriever = DualStrategyRrfRetriever(self._vault, self._config)
        self._gate = BatchQueriesCoalescingGate(self._retriever, self._config)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def config(self) -> EphemeralFts5Config:
        return self._config

    @property
    def vault(self) -> EphemeralSqliteFts5Vault:
        return self._vault

    def index_markdown_document(
        self,
        document_id: str,
        content: str,
    ) -> IndexReceipt:
        """Parses markdown preserving code blocks and writes into dual FTS5 virtual tables."""
        chunks = self._chunker.chunk_document(
            document_id=document_id,
            content=content,
            session_id=self._session_id,
        )
        return self._vault.index_chunks(document_id=document_id, chunks=chunks)

    def batch_search(
        self,
        queries: Sequence[str | SearchQueryItem],
        default_top_k: int = 4,
    ) -> BatchSearchReceipt:
        """Coalesces all query requests into a single round and returns structured context blocks."""
        return self._gate.execute_batch(
            session_id=self._session_id,
            queries=queries,
            default_top_k=default_top_k,
        )

    def search_single(
        self,
        query: str | SearchQueryItem,
    ) -> Sequence[SearchResultChunk]:
        """Performs a single dual-strategy RRF query."""
        return self._retriever.search(query)

    def delete_document(self, document_id: str) -> int:
        """Removes a document and its indexed chunks from the ephemeral vault."""
        return self._vault.delete_document(document_id)

    def get_stats(self) -> dict[str, int]:
        """Returns document, chunk, and token statistics for this session vault."""
        return self._vault.get_stats()

    def destroy(self) -> None:
        """Destroys and cleans up the ephemeral session vault and physical storage."""
        self._vault.destroy()
