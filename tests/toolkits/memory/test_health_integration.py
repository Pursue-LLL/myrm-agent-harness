"""Integration tests for MemoryManager.compute_health_score().

Tests the data collection and orchestration in compute_health_score(),
using mock backends to verify correct delegation to compute_health().
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.health import HealthScore
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument


def _make_doc(
    *,
    doc_id: str = "doc-1",
    user_id: str = "test-user",
    days_ago: int = 1,
    importance: float = 0.5,
    access_count: int = 5,
    last_accessed_days_ago: int | None = None,
    archived: bool = False,
) -> VectorDocument:
    now = datetime.now(UTC)
    created = now - timedelta(days=days_ago)
    last_accessed = (
        (now - timedelta(days=last_accessed_days_ago)).isoformat() if last_accessed_days_ago is not None else ""
    )
    return VectorDocument(
        id=doc_id,
        content=f"test memory {doc_id}",
        embedding=[0.1] * 10,
        metadata={
            "memory_type": "semantic",
            "importance": importance,
            "confidence": 1.0,
            "access_count": access_count,
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
            "last_accessed_at": last_accessed,
            "archived": archived,
            "tags": "[]",
            "preference_type": "",
            "preference_strength": 0.0,
            "source_chat_id": "",
            "source_message_id": "",
            "correction_of": "",
            "source_error": "",
            "language": "en",
            "merge_count": 0,
            "merge_history": "",
        },
    )


def _create_manager(
    memory_config: MemoryConfig,
    mock_vector_store: AsyncMock,
    mock_embedding: AsyncMock,
    mock_graph_store: AsyncMock | None = None,
) -> MemoryManager:
    return MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
        embedding=mock_embedding,
        graph=mock_graph_store,
        auto_warmup=False,
    )


@pytest.fixture
def _docs_fresh() -> list[VectorDocument]:
    return [_make_doc(doc_id=f"fresh-{i}", days_ago=i) for i in range(5)]


@pytest.fixture
def _docs_stale() -> list[VectorDocument]:
    return [_make_doc(doc_id=f"stale-{i}", days_ago=60 + i) for i in range(5)]


class TestComputeHealthScore:
    @pytest.mark.asyncio
    async def test_empty_system_returns_100(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        result = await mgr.compute_health_score()

        assert isinstance(result, HealthScore)
        assert result.total == 100
        assert result.sample_size == 0
        assert result.has_graph is False

    @pytest.mark.asyncio
    async def test_returns_health_score_type(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        _docs_fresh: list[VectorDocument],
    ) -> None:
        mock_vector_store.scroll.return_value = _docs_fresh
        mock_vector_store.count.return_value = 5

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        result = await mgr.compute_health_score()

        assert isinstance(result, HealthScore)
        assert result.total > 0
        assert result.sample_size > 0
        assert "freshness" in result.dimensions
        assert "retention_health" in result.dimensions

    @pytest.mark.asyncio
    async def test_to_dict_works(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        result = await mgr.compute_health_score()
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "total" in d
        assert "dimensions" in d
        assert "suggestions" in d

    @pytest.mark.asyncio
    async def test_with_graph_includes_coherence(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_graph_store: AsyncMock,
        _docs_fresh: list[VectorDocument],
    ) -> None:
        mock_vector_store.scroll.return_value = _docs_fresh
        mock_vector_store.count.return_value = 5
        mock_graph_store.get_related_nodes.return_value = ["related-1"]

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding, mock_graph_store)
        result = await mgr.compute_health_score()

        assert result.has_graph is True
        assert "coherence" in result.dimensions
        assert result.dimensions["coherence"] == 1.0

    @pytest.mark.asyncio
    async def test_without_graph_no_coherence(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        _docs_fresh: list[VectorDocument],
    ) -> None:
        mock_vector_store.scroll.return_value = _docs_fresh
        mock_vector_store.count.return_value = 5

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding, None)
        result = await mgr.compute_health_score()

        assert result.has_graph is False
        assert "coherence" not in result.dimensions

    @pytest.mark.asyncio
    async def test_count_failure_handled_gracefully(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = [_make_doc()]
        mock_vector_store.count.side_effect = RuntimeError("DB down")

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        result = await mgr.compute_health_score()

        assert isinstance(result, HealthScore)
        assert result.sample_size > 0

    @pytest.mark.asyncio
    async def test_graph_failure_handled_gracefully(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        mock_vector_store.scroll.return_value = [_make_doc()]
        mock_vector_store.count.return_value = 1
        mock_graph_store.get_related_nodes.side_effect = RuntimeError("Graph error")

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding, mock_graph_store)
        result = await mgr.compute_health_score()

        assert result.has_graph is True
        assert result.dimensions.get("coherence", 0.0) == 0.0

    @pytest.mark.asyncio
    async def test_concurrent_coherence_collection(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """Verify coherence checks run concurrently via asyncio.gather."""
        docs = [_make_doc(doc_id=f"c-{i}") for i in range(5)]
        mock_vector_store.scroll.return_value = docs
        mock_vector_store.count.return_value = 5

        call_count = 0

        async def _track_related(mem_id: str) -> list[str]:
            nonlocal call_count
            call_count += 1
            return ["rel"] if call_count % 2 == 0 else []

        mock_graph_store.get_related_nodes.side_effect = _track_related

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding, mock_graph_store)
        result = await mgr.compute_health_score()

        # scroll is called for both SEMANTIC and EPISODIC, each returning 5 docs = 10 total
        assert mock_graph_store.get_related_nodes.call_count == 10
        assert result.dimensions["coherence"] == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_public_api_import(self) -> None:
        """Verify HealthScore is importable from the public API."""
        from myrm_agent_harness.toolkits.memory import HealthScore as PublicHealthScore

        assert PublicHealthScore is HealthScore
