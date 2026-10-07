# [POS]: tests/unit/toolkits/memory/test_zero_config_hybrid_memory_suite.py
# [INPUT]: In-memory SQLite FTS5 engine, OfflineSynonymExpander, DualDriveHybridMemoryEngine
# [OUTPUT]: Unit test suite verifying FTS5 CRUD, synonym expansion, dual-drive RRF fusion, and graceful degradation

from pathlib import Path

from myrm_agent_harness.toolkits.memory import (
    DualDriveHybridMemoryEngine,
    HybridMemoryItem,
    HybridSearchResult,
    OfflineSynonymExpander,
    RetrievalMode,
    SqliteFts5Engine,
)


def test_sqlite_fts5_engine_crud_and_bm25_search(tmp_path: Path) -> None:
    """Verifies SQLite FTS5 virtual table initialization, unicode61 indexing, and CRUD."""
    db_file = tmp_path / "test_fts5.db"
    engine = SqliteFts5Engine(db_path=db_file)

    item1 = HybridMemoryItem(
        item_id="item_001",
        title="JWT Token Authentication Architecture",
        content="All public API endpoints require bearer token verification in sandbox mode.",
        tags=["auth", "security"],
        metadata={"priority": 1, "owner": "secops"},
    )
    item2 = HybridMemoryItem(
        item_id="item_002",
        title="SQLite FTS5 Local Storage Guide",
        content="Embedded SQLite virtual tables provide sub-millisecond full text search capabilities.",
        tags=["storage", "sqlite"],
        metadata={"priority": 2, "owner": "core"},
    )

    engine.insert_or_replace_item(item1)
    engine.insert_or_replace_item(item2)
    assert engine.count_items() == 2

    # Verify retrieval by item_id
    fetched = engine.get_item("item_001")
    assert fetched is not None
    assert fetched.title == "JWT Token Authentication Architecture"
    assert fetched.metadata.get("owner") == "secops"

    # Search FTS5 with BM25 ranking
    hits = engine.search_fts('"token" AND "authentication"', limit=5)
    assert len(hits) == 1
    assert hits[0].item_id == "item_001"
    assert hits[0].score > 0.0

    # Delete item and verify deletion
    deleted = engine.delete_item("item_001")
    assert deleted is True
    assert engine.count_items() == 1
    assert engine.get_item("item_001") is None
    engine.close()


def test_synonym_expander_query_expansion_and_safe_grouping() -> None:
    """Verifies built-in engineering synonym clusters, query expansion, and safe sanitization."""
    expander = OfflineSynonymExpander()

    # 1. Builtin expansion: "oom" should expand to out_of_memory, memory_leak, heap_overflow
    expr, expanded = expander.expand_query("critical oom failure")
    assert "critical" in expr
    assert "oom" in expr
    assert "memory_leak" in expr or "out_of_memory" in expr
    assert any("out_of_memory" in term for term in expanded)

    # 2. Chinese synonym expansion
    expr_zh, expanded_zh = expander.expand_query("火锅")
    assert "火锅" in expr_zh
    assert "打边炉" in expr_zh
    assert "打边炉" in expanded_zh

    # 3. Dynamic synonym registration
    expander.register_synonyms("grpc", ["protobuf", "rpc", "transport"])
    syns = expander.get_synonyms("grpc")
    assert "protobuf" in syns
    assert "transport" in syns
    # Bidirectional verification
    assert "grpc" in expander.get_synonyms("protobuf")

    # 4. Safe sanitization against SQL/FTS syntax breakages
    safe_expr, _ = expander.expand_query('auth "injection\' OR 1=1 * :')
    assert "auth" in safe_expr


def test_dual_drive_rrf_hybrid_fusion() -> None:
    """Verifies RRF reciprocal rank fusion across both lexical FTS5 and dense vector channels."""
    engine = DualDriveHybridMemoryEngine(db_path=":memory:", rrf_k=60)

    # Insert items into FTS engine
    engine.insert_item(
        HybridMemoryItem(
            item_id="doc_a",
            title="Authentication Guardrails",
            content="Bearer tokens and JWT verification for all gateways.",
        )
    )
    engine.insert_item(
        HybridMemoryItem(
            item_id="doc_b",
            title="Database Connection Pool",
            content="SQLite database connection pool management.",
        )
    )

    # Provide a mock dense vector provider
    def mock_vector_provider(query: str, limit: int) -> list[HybridSearchResult]:
        return [
            HybridSearchResult(
                item_id="doc_b",
                title="Database Connection Pool",
                content="SQLite database connection pool management.",
                score=0.95,
                source_channel="vector",
                rank=1,
            ),
            HybridSearchResult(
                item_id="doc_a",
                title="Authentication Guardrails",
                content="Bearer tokens and JWT verification for all gateways.",
                score=0.72,
                source_channel="vector",
                rank=2,
            ),
        ]

    engine.set_dense_vector_provider(mock_vector_provider)

    results, mode = engine.search("authentication tokens", limit=5)
    assert mode == RetrievalMode.HYBRID_RRF
    assert len(results) == 2
    # Verify RRF channel annotation
    assert results[0].source_channel == "rrf_hybrid"
    # Both channels ranked doc_a high in lexical or vector
    assert any(r.item_id == "doc_a" for r in results)
    assert any(r.item_id == "doc_b" for r in results)


def test_dual_drive_graceful_degradation_on_vector_failure() -> None:
    """Verifies seamless fallback to pure FTS5 when vector provider raises exceptions or times out."""
    engine = DualDriveHybridMemoryEngine(db_path=":memory:")

    engine.insert_item(
        HybridMemoryItem(
            item_id="doc_resilient",
            title="Resilient Sandbox Architecture",
            content="Local first offline memory resilience without remote API requirement.",
        )
    )

    # Vector provider that simulates network failure / timeout
    def failing_vector_provider(query: str, limit: int) -> list[HybridSearchResult]:
        raise ConnectionError("Remote Embedding API unreachable in air-gapped sandbox")

    engine.set_dense_vector_provider(failing_vector_provider)

    # Execute search - must NOT raise ConnectionError, must degrade gracefully
    results, mode = engine.search("sandbox offline resilience", limit=5)
    assert mode == RetrievalMode.DEGRADED_FALLBACK
    assert len(results) == 1
    assert results[0].item_id == "doc_resilient"
    assert results[0].source_channel == "fts_degraded"

    # Telemetry stats check
    stats = engine.get_stats()
    assert stats.total_items == 1
    assert stats.dense_vector_available is True
