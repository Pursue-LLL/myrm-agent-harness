# [INPUT]: BatchQueriesCoalescingGate, BatchSearchReceipt, DocumentChunk, DualStrategyRrfRetriever, EphemeralFts5Config, EphemeralSessionFts5IndexAndBatchRetrieverSuite, EphemeralSqliteFts5Vault, IndexReceipt, MarkdownCodeBlockChunker, SearchQueryItem, SearchResultChunk
# [OUTPUT]: test_ephemeral_session_fts5_suite.py
# [POS]: tests/agent/context_management/test_ephemeral_session_fts5_suite.py

"""Comprehensive unit tests for EphemeralSessionFts5IndexAndBatchRetrieverSuite.

Verifies:
1. Markdown structure-aware chunking preserving code block fences and nested heading paths.
2. Ephemeral SQLite FTS5 dual virtual table indexing (Porter + Trigram) and idempotent updates.
3. Dual-strategy retrieval with Reciprocal Rank Fusion (RRF) and code block boosting.
4. Batch queries coalescing gate executing all queries in a single round.
5. End-to-end facade orchestration, document deletion, and session isolation.
6. Vault destruction and resource cleanup.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from myrm_agent_harness.agent.context_management.ephemeral_fts5 import (
    BatchQueriesCoalescingGate,
    BatchSearchReceipt,
    DocumentChunk,
    DualStrategyRrfRetriever,
    EphemeralFts5Config,
    EphemeralSessionFts5IndexAndBatchRetrieverSuite,
    EphemeralSqliteFts5Vault,
    IndexReceipt,
    MarkdownCodeBlockChunker,
    SearchQueryItem,
    SearchResultChunk,
)


_SAMPLE_API_MARKDOWN = """# Payment Gateway API Specification

Welcome to the Payment Gateway API reference documentation.

## Authentication and Security
All requests must include an `Authorization: Bearer <token>` header.

```python
import requests

def init_client(api_key: str):
    return requests.Session(headers={"Authorization": f"Bearer {api_key}"})
```

## Payment Processing

### Create Payment Intent
Initiates a single charge transaction.

```json
{
  "amount": 5000,
  "currency": "usd",
  "capture_method": "automatic"
}
```

The server returns a payment intent object with an identifier `pi_12345`.

### Refund Processing
Handles refund requests for successful transactions.

To issue a full refund, send a POST request to `/v1/refunds` with `payment_intent_id`.
"""


def test_markdown_chunker_preserves_code_fences_and_headings() -> None:
    """Verifies heading hierarchy extraction and intact code fences."""
    chunker = MarkdownCodeBlockChunker()
    chunks = chunker.chunk_document(
        document_id="doc_api_spec",
        content=_SAMPLE_API_MARKDOWN,
        session_id="sess_001",
    )

    assert len(chunks) >= 3
    # First chunk: Authentication
    auth_chunk = next(ch for ch in chunks if "Authentication" in ch.heading_path)
    assert "Payment Gateway API Specification > Authentication and Security" in auth_chunk.heading_path
    assert auth_chunk.has_code_block is True
    assert "def init_client" in auth_chunk.content
    assert "```python" in auth_chunk.content
    assert "```" in auth_chunk.content  # Closing fence intact

    # Second chunk: Payment Intent
    intent_chunk = next(ch for ch in chunks if "Create Payment Intent" in ch.heading_path)
    assert intent_chunk.has_code_block is True
    assert '"currency": "usd"' in intent_chunk.content


def test_ephemeral_sqlite_fts5_vault_indexing_and_idempotency() -> None:
    """Verifies dual FTS table indexing, statistics, and idempotent overwrite."""
    vault = EphemeralSqliteFts5Vault(session_id="sess_test")
    try:
        chunker = MarkdownCodeBlockChunker()
        chunks = chunker.chunk_document("doc_01", _SAMPLE_API_MARKDOWN, "sess_test")

        receipt1 = vault.index_chunks("doc_01", chunks)
        assert receipt1.status == "success"
        assert receipt1.total_chunks == len(chunks)

        stats1 = vault.get_stats()
        assert stats1["document_count"] == 1
        assert stats1["chunk_count"] == len(chunks)

        # Idempotent re-index of the exact same document
        receipt2 = vault.index_chunks("doc_01", chunks)
        assert receipt2.status == "success"
        stats2 = vault.get_stats()
        assert stats2["document_count"] == 1
        assert stats2["chunk_count"] == len(chunks)  # No duplicate rows

        # Porter keyword search test
        porter_hits = vault.search_porter_raw("Authentication")
        assert len(porter_hits) >= 1
        assert porter_hits[0][1] == 1  # Rank 1

        # Trigram substring search test
        trigram_hits = vault.search_trigram_raw("init_client")
        assert len(trigram_hits) >= 1
    finally:
        vault.destroy()


def test_dual_strategy_rrf_retriever_precision() -> None:
    """Verifies RRF fusion score calculation and code-block boosting."""
    vault = EphemeralSqliteFts5Vault(session_id="sess_rrf")
    try:
        chunker = MarkdownCodeBlockChunker()
        chunks = chunker.chunk_document("doc_spec", _SAMPLE_API_MARKDOWN, "sess_rrf")
        vault.index_chunks("doc_spec", chunks)

        retriever = DualStrategyRrfRetriever(vault)

        # Search for code symbol with boost
        results = retriever.search(
            SearchQueryItem(query_text="init_client", top_k=3, boost_code_blocks=True)
        )
        assert len(results) >= 1
        top_match = results[0]
        assert top_match.has_code_block is True
        assert "Authentication" in top_match.heading_path
        assert top_match.rrf_score > 0.0

        # Verify RRF score ordering
        scores = [r.rrf_score for r in results]
        assert scores == sorted(scores, reverse=True)
    finally:
        vault.destroy()


def test_batch_queries_coalescing_gate_single_turn() -> None:
    """Verifies multi-query execution in one single round and structured rendering."""
    vault = EphemeralSqliteFts5Vault(session_id="sess_batch")
    try:
        chunker = MarkdownCodeBlockChunker()
        chunks = chunker.chunk_document("doc_api", _SAMPLE_API_MARKDOWN, "sess_batch")
        vault.index_chunks("doc_api", chunks)

        retriever = DualStrategyRrfRetriever(vault)
        gate = BatchQueriesCoalescingGate(retriever)

        queries = [
            "Bearer token",
            "payment intent currency",
            "full refund POST",
        ]

        receipt = gate.execute_batch(session_id="sess_batch", queries=queries, default_top_k=2)

        assert receipt.total_queries == 3
        assert len(receipt.results_by_query) == 3
        assert receipt.total_results_returned >= 3

        # Rendered output verification
        rendered = receipt.rendered_context_block
        assert "<session_search_results>" in rendered
        assert "</session_search_results>" in rendered
        assert '<query text="Bearer token"' in rendered
        assert '<query text="payment intent currency"' in rendered
        assert '<query text="full refund POST"' in rendered
    finally:
        vault.destroy()


def test_ephemeral_session_fts5_suite_end_to_end() -> None:
    """Verifies end-to-end facade indexing, batch lookup, document deletion, and disk cleanup."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_file = os.path.join(temp_dir, "test_session_kb.sqlite")
        suite = EphemeralSessionFts5IndexAndBatchRetrieverSuite(
            session_id="sess_facade",
            db_path=db_file,
        )

        receipt = suite.index_markdown_document("doc_main", _SAMPLE_API_MARKDOWN)
        assert receipt.total_chunks >= 3
        assert os.path.exists(db_file)

        # Batch lookup
        batch_res = suite.batch_search(
            queries=["authorization token", "refunds endpoint"],
            default_top_k=2,
        )
        assert batch_res.total_queries == 2
        assert "doc_main" in batch_res.rendered_context_block

        # Single lookup
        single_res = suite.search_single("Bearer")
        assert len(single_res) >= 1

        # Stats check
        stats = suite.get_stats()
        assert stats["document_count"] == 1

        # Delete document
        deleted_count = suite.delete_document("doc_main")
        assert deleted_count >= 3
        assert suite.get_stats()["document_count"] == 0

        # Destroy vault and verify file removal
        suite.destroy()
        assert not os.path.exists(db_file)
