"""Tests for Exact Fact Deterministic Hard Lock and Dual-Track Search.

Covers:
- ExactFactClassifier identification (UUID, Git SHA, SemVer, Port, Config Key)
- Shannon entropy and false positive suppression
- BaseMemory.is_user_protected and ForgettingStrategy immunity
- SQLiteRelationalStore exact fact persistence, search_fts5, and deletion
- MemoryRetriever deterministic exact-fact boosting
- MemoryWriter write-time exact fact recognition
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.relational.sqlite_store import SQLiteRelationalStore
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.strategies.exact_fact import (
    ExactFactClassifier,
    compute_shannon_entropy,
)
from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettingStrategy
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


class TestExactFactClassifier:
    def test_uuid_extraction(self) -> None:
        text = "The host identifier is 123e4567-e89b-12d3-a456-426614174000 in cluster."
        identifiers = ExactFactClassifier.extract_identifiers(text)
        assert "123e4567-e89b-12d3-a456-426614174000" in identifiers
        is_exact, idents = ExactFactClassifier.classify(text)
        assert is_exact is True
        assert "123e4567-e89b-12d3-a456-426614174000" in idents

    def test_git_sha_extraction(self) -> None:
        text = "Rolled back release to git commit a1b2c3d4e5f60718293a4b5c6d7e8f9012345678 due to bug."
        identifiers = ExactFactClassifier.extract_identifiers(text)
        assert "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" in identifiers
        is_exact, idents = ExactFactClassifier.classify(text)
        assert is_exact is True
        assert "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" in idents

    def test_semver_extraction(self) -> None:
        text = "Upgraded runtime dependency to v2.14.3-alpha.1 successfully."
        identifiers = ExactFactClassifier.extract_identifiers(text)
        assert any("2.14.3" in ident for ident in identifiers)
        is_exact, idents = ExactFactClassifier.classify(text)
        assert is_exact is True
        assert any("2.14.3" in ident for ident in idents)

    def test_port_and_endpoint_extraction(self) -> None:
        text = "Internal telemetry collector is listening on port :9090 or localhost:8080."
        identifiers = ExactFactClassifier.extract_identifiers(text)
        assert any("9090" in ident or "8080" in ident for ident in identifiers)
        is_exact, _idents = ExactFactClassifier.classify(text)
        assert is_exact is True

    def test_config_key_extraction(self) -> None:
        text = "Please set API_GATEWAY_TIMEOUT_MS and DATABASE_MAX_CONNECTIONS in .env."
        identifiers = ExactFactClassifier.extract_identifiers(text)
        assert "API_GATEWAY_TIMEOUT_MS" in identifiers
        assert "DATABASE_MAX_CONNECTIONS" in identifiers
        is_exact, idents = ExactFactClassifier.classify(text)
        assert is_exact is True
        assert "API_GATEWAY_TIMEOUT_MS" in idents

    def test_shannon_entropy_calculation(self) -> None:
        low_entropy = compute_shannon_entropy("aaaaaaaaaaaa")
        high_entropy = compute_shannon_entropy("a1B#9$xZ7!kQ")
        assert high_entropy > low_entropy
        assert high_entropy > 3.0

    def test_common_text_no_false_positive(self) -> None:
        text = "We should meet tomorrow afternoon to discuss product design requirements."
        identifiers = ExactFactClassifier.extract_identifiers(text)
        assert len(identifiers) == 0
        is_exact, idents = ExactFactClassifier.classify(text)
        assert is_exact is False
        assert len(idents) == 0


class TestExactFactMemoryProtection:
    def test_base_memory_protection_flag(self) -> None:
        m = SemanticMemory(content="Regular preference", is_exact_fact=False)
        assert not m.is_user_protected

        m_exact = SemanticMemory(
            content="Host uuid 123e4567-e89b-12d3-a456-426614174000",
            is_exact_fact=True,
            exact_identifiers=["123e4567-e89b-12d3-a456-426614174000"],
        )
        assert m_exact.is_user_protected is True

    def test_forgetting_strategy_immunity(self) -> None:
        strategy = ForgettingStrategy()
        m = SemanticMemory(
            content="Host uuid 123e4567-e89b-12d3-a456-426614174000",
            importance=0.001,
            access_count=0,
            created_at=datetime.now(UTC) - timedelta(days=500),
            is_exact_fact=True,
        )
        result = strategy.calculate_retention_score(m)
        assert not result.should_forget
        assert "Protected" in result.reason


@pytest.mark.asyncio
class TestExactFactSQLiteStore:
    async def test_record_search_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_memory.db")
            store = SQLiteRelationalStore(db_path=db_path)

            memory_id = "mem_fact_001"
            content = "Production server uuid 123e4567-e89b-12d3-a456-426614174000 is online on port 9090."
            identifiers = ["123e4567-e89b-12d3-a456-426614174000", "9090"]

            # Record exact fact
            await store.record_exact_fact(
                memory_id=memory_id,
                user_id="user_test",
                content=content,
                identifiers=identifiers,
                primary_namespace="ops",
            )

            # Search exact identifier
            results = await store.search_fts5("123e4567-e89b-12d3-a456-426614174000", limit=5)
            assert len(results) >= 1
            assert results[0].id == memory_id
            assert results[0].memory.is_exact_fact is True
            assert "123e4567-e89b-12d3-a456-426614174000" in results[0].memory.exact_identifiers

            # Search non-matching
            no_results = await store.search_fts5("non_existing_random_sha_or_uuid", limit=5)
            assert len(no_results) == 0

            # Delete
            await store.delete_exact_fact(memory_id)

            # Search after deletion
            results_after = await store.search_fts5("123e4567-e89b-12d3-a456-426614174000", limit=5)
            assert len(results_after) == 0

            await store.close()


class TestRetrieverExactFactBoosting:
    def test_boost_exact_fact_top_rank(self) -> None:
        retriever = MemoryRetriever()

        exact_mem = SemanticMemory(
            id="exact_1",
            content="Host uuid 123e4567-e89b-12d3-a456-426614174000 on node-0",
            is_exact_fact=True,
            exact_identifiers=["123e4567-e89b-12d3-a456-426614174000"],
        )
        vague_mem = SemanticMemory(
            id="vague_2",
            content="Some generic cloud server information and guidelines",
            importance=0.99,
        )

        r_exact = MemorySearchResult(memory=exact_mem, score=0.6, memory_type=MemoryType.SEMANTIC)
        r_vague = MemorySearchResult(memory=vague_mem, score=0.95, memory_type=MemoryType.SEMANTIC)

        fused = retriever.fuse(
            [[r_vague, r_exact]],
            limit=2,
            query="What is the IP of host 123e4567-e89b-12d3-a456-426614174000?",
        )

        assert len(fused) == 2
        # Exact fact must be ranked #1 due to deterministic hard lock boost
        assert fused[0].id == "exact_1"
        assert fused[0].memory.is_exact_fact is True


@pytest.mark.asyncio
class TestMemoryManagerExactFactEndToEnd:
    async def test_manager_write_exact_fact_and_delete_cascade(
        self,
        memory_config,
        mock_vector_store,
        mock_embedding,
    ) -> None:
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_memory.db")
            store = SQLiteRelationalStore(db_path=db_path)
            manager = MemoryManager(
                memory_config,
                user_id="user_admin",
                vector=mock_vector_store,
                embedding=mock_embedding,
                relational=store,
                fts5_searcher=store.search_fts5,
            )

            # Store memory containing exact UUID
            mem = await manager.store(
                SemanticMemory(
                    content="Critical cluster coordinator node uuid 123e4567-e89b-12d3-a456-426614174000 port 9090",
                )
            )

            assert mem.is_exact_fact is True
            assert "123e4567-e89b-12d3-a456-426614174000" in mem.exact_identifiers
            assert mem.is_user_protected is True

            # Direct FTS5 search
            fts_hits = await store.search_fts5("123e4567-e89b-12d3-a456-426614174000", limit=5)
            assert len(fts_hits) >= 1
            assert fts_hits[0].id == mem.id

            # Delete memory and assert cascade cleanup
            from myrm_agent_harness.toolkits.vector.base import VectorDocument

            mock_vector_store.get.return_value = [
                VectorDocument(
                    id=mem.id,
                    content=mem.content,
                    vector=[0.1] * 768,
                    metadata={
                        "user_id": "user_admin",
                        "primary_namespace": "agent:default",
                        "namespaces": ["global", "agent:default"],
                    },
                )
            ]
            await manager.delete_memory(manager._config.semantic_collection, [mem.id])
            fts_hits_after = await store.search_fts5("123e4567-e89b-12d3-a456-426614174000", limit=5)
            assert len(fts_hits_after) == 0

            await manager.close()

