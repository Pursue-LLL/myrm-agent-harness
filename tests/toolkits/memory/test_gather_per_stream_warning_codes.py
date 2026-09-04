"""Tests for GatherPerStreamTypedWarningCodes across multi-stream recall."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
    search_memory_corpus,
    search_sessions_corpus,
    search_wiki_corpus,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchBackends,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RetrievalConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.observability import (
    GATHER_EPISODIC_FAILED,
    GATHER_EPISODIC_TIMEOUT,
    GATHER_GRAPH_TIMEOUT,
    GATHER_PROCEDURAL_FAILED,
    GATHER_PROFILE_FAILED,
    GATHER_QUERY_EMBEDDING_FAILED,
    GATHER_QUERY_EMBEDDING_TIMEOUT,
    GATHER_SEMANTIC_FAILED,
    GATHER_SEMANTIC_TIMEOUT,
    GATHER_SESSIONS_TIMEOUT,
    GATHER_WIKI_TIMEOUT,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult
from myrm_agent_harness.toolkits.memory.reliability import MemoryGatherWarningCode
from myrm_agent_harness.toolkits.memory.types import MemoryType, ProfileEntry


@pytest.fixture
def fast_timeout_config() -> MemoryConfig:
    return MemoryConfig(
        embedding_model="test-model",
        collection_prefix="test_memory",
        retrieval=RetrievalConfig(timeout_seconds=0.05),
    )


class TestGatherWarningCodesEnum:
    def test_enum_members_and_str_compatibility(self) -> None:
        assert MemoryGatherWarningCode.GATHER_EMBED_TIMEOUT == "GATHER_EMBED_TIMEOUT"
        assert MemoryGatherWarningCode.GATHER_SEMANTIC_TIMEOUT == "GATHER_SEMANTIC_TIMEOUT"
        assert MemoryGatherWarningCode.GATHER_GRAPH_TIMEOUT == "GATHER_GRAPH_TIMEOUT"
        assert MemoryGatherWarningCode.GATHER_WIKI_TIMEOUT == "GATHER_WIKI_TIMEOUT"
        assert MemoryGatherWarningCode.GATHER_SESSIONS_TIMEOUT == "GATHER_SESSIONS_TIMEOUT"
        assert isinstance(MemoryGatherWarningCode.GATHER_VECTOR_FAILED, str)


class TestSearchServiceWarningCodesCollection:
    @pytest.mark.asyncio
    async def test_embed_timeout_records_warning_code(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        async def _hang_embed(*args: object, **kwargs: object) -> list[float]:
            await asyncio.sleep(0.5)
            return [0.1] * 768

        mock_embedding.embed.side_effect = _hang_embed

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            embedding=mock_embedding,
            vector=mock_vector_store,
        )

        results = await manager.search("test query", memory_types=[MemoryType.SEMANTIC])
        assert results == []

        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_QUERY_EMBEDDING_TIMEOUT in trace.warning_codes

    @pytest.mark.asyncio
    async def test_vector_search_timeout_records_stream_warning_code(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.return_value = [0.1] * 768

        async def _hang_search(*args: object, **kwargs: object) -> list[VectorSearchResult]:
            await asyncio.sleep(0.5)
            return []

        mock_vector_store.search.side_effect = _hang_search

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            embedding=mock_embedding,
            vector=mock_vector_store,
        )

        results = await manager.search("test query", memory_types=[MemoryType.SEMANTIC])
        assert results == []

        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_SEMANTIC_TIMEOUT in trace.warning_codes

    @pytest.mark.asyncio
    async def test_store_error_records_failed_code(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.search.side_effect = RuntimeError("vector store connection refused")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            embedding=mock_embedding,
            vector=mock_vector_store,
        )

        results = await manager.search("test query", memory_types=[MemoryType.SEMANTIC])
        assert results == []

        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_SEMANTIC_FAILED in trace.warning_codes

    @pytest.mark.asyncio
    async def test_graph_timeout_records_warning_code(
        self,
        mock_vector_store,
        mock_embedding,
        mock_graph_store,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="mem-1",
                    content="Relevant content",
                    vector=[0.1] * 768,
                    metadata={"memory_type": "semantic", "channel_id": "default"},
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.9,
            )
        ]

        async def _hang_graph(*args: object, **kwargs: object) -> list[object]:
            await asyncio.sleep(0.5)
            return []

        mock_graph_store.find_nodes.side_effect = _hang_graph

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            embedding=mock_embedding,
            vector=mock_vector_store,
            graph=mock_graph_store,
        )

        results = await manager.search("test query", memory_types=[MemoryType.SEMANTIC])
        assert len(results) == 1

        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_GRAPH_TIMEOUT in trace.warning_codes

    @pytest.mark.asyncio
    async def test_healthy_search_has_zero_warnings(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.scroll.return_value = []
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="mem-ok",
                    content="Zero warning healthy memory",
                    vector=[0.1] * 768,
                    metadata={"memory_type": "semantic", "channel_id": "default"},
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.95,
            )
        ]

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            embedding=mock_embedding,
            vector=mock_vector_store,
        )

        results = await manager.search("clean query", memory_types=[MemoryType.SEMANTIC])
        assert len(results) == 1

        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is False
        assert trace.warning_codes == []

    @pytest.mark.asyncio
    async def test_graph_enrichment_error_records_failed_code(
        self,
        mock_relational_store,
        mock_graph_store,
        fast_timeout_config,
    ) -> None:
        mock_graph_store.find_nodes.side_effect = RuntimeError("graph db crashed")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            relational=mock_relational_store,
            graph=mock_graph_store,
            auto_warmup=False,
        )

        results = await manager.search(
            "timezone query",
            memory_types=[MemoryType.PROFILE],
            limit=10,
            use_rrf=False,
        )

        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_GRAPH_FAILED in trace.warning_codes

    @pytest.mark.asyncio
    async def test_episodic_search_stream_tasks(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.side_effect = RuntimeError("qdrant episodic failure")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search(
            "yesterday summary",
            memory_types=[MemoryType.EPISODIC],
            limit=10,
            use_rrf=False,
        )

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_EPISODIC_FAILED in trace.warning_codes

    @pytest.mark.asyncio
    async def test_conversation_search_stream_tasks(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.side_effect = RuntimeError("qdrant conversation failure")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search(
            "last turn details",
            memory_types=[MemoryType.CONVERSATION],
            limit=10,
            use_rrf=False,
        )

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_CONVERSATION_FAILED in trace.warning_codes

    @pytest.mark.asyncio
    async def test_procedural_error_records_failed_code(
        self,
        mock_relational_store,
        fast_timeout_config,
    ) -> None:
        mock_relational_store.search_rules.side_effect = RuntimeError("database locked")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            relational=mock_relational_store,
            auto_warmup=False,
        )

        results = await manager.search(
            "rules",
            memory_types=[MemoryType.PROCEDURAL],
            limit=10,
            use_rrf=False,
        )

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_PROCEDURAL_FAILED in trace.warning_codes

    @pytest.mark.asyncio
    async def test_profile_error_records_failed_code(
        self,
        mock_relational_store,
        fast_timeout_config,
    ) -> None:
        mock_relational_store.list_profiles.side_effect = RuntimeError("sqlite disk I/O error")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            relational=mock_relational_store,
            auto_warmup=False,
        )

        results = await manager.search(
            "timezone",
            memory_types=[MemoryType.PROFILE],
            limit=10,
            use_rrf=False,
        )

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_PROFILE_FAILED in trace.warning_codes

    @pytest.mark.asyncio
    async def test_query_embedding_error_records_failed_code(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.side_effect = RuntimeError("OpenAI Embedding 503 Service Unavailable")
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = []

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search(
            "weather query",
            memory_types=[MemoryType.SEMANTIC],
            limit=10,
            use_rrf=False,
        )

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_QUERY_EMBEDDING_FAILED in trace.warning_codes

    @pytest.mark.asyncio
    async def test_multi_stream_partial_failures_accumulate_warning_codes(
        self,
        mock_relational_store,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_relational_store.list_profiles.side_effect = RuntimeError("table corrupt")
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1

        async def _hang_vector(*args: object, **kwargs: object) -> list[object]:
            await asyncio.sleep(0.5)
            return []

        mock_vector_store.search.side_effect = _hang_vector

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search(
            "hybrid test",
            memory_types=[MemoryType.PROFILE, MemoryType.SEMANTIC],
            limit=10,
            use_rrf=False,
        )

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert GATHER_PROFILE_FAILED in trace.warning_codes
        assert GATHER_SEMANTIC_TIMEOUT in trace.warning_codes


class TestAgentSurfaceToolDegradationHonesty:
    @pytest.mark.asyncio
    async def test_empty_search_with_degradation_reports_typed_codes(
        self,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
    ) -> None:
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.search.side_effect = RuntimeError("disk io error")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            embedding=mock_embedding,
            vector=mock_vector_store,
        )

        category_map = {"knowledge": MemoryType.SEMANTIC}
        res_str = await search_memory_corpus(
            manager,
            query="test",
            category_to_type=category_map,
            categories=["knowledge"],
            limit=5,
            since=None,
            until=None,
        )
        assert "Memory search degraded due to timeout or internal store error (GATHER_SEMANTIC_FAILED)" in res_str

    @pytest.mark.asyncio
    async def test_wiki_and_sessions_timeout_notice(self) -> None:
        backends = MagicMock(spec=MemorySearchBackends)

        async def _hang_wiki(query: str) -> object:
            await asyncio.sleep(0.5)
            return None

        backends.query_wiki = _hang_wiki
        backends.wiki_structure = None
        backends.wiki_agent_id = None

        wiki_out = await search_wiki_corpus(backends, "test wiki", timeout_seconds=0.01)
        assert isinstance(wiki_out, str)
        assert "GATHER_WIKI_TIMEOUT" in wiki_out

        provider = MagicMock()

        async def _hang_sessions(req: object) -> object:
            await asyncio.sleep(0.5)
            return None

        provider.search = _hang_sessions
        backends.conversation_provider = provider

        sess_out = await search_sessions_corpus(
            backends,
            query="test session",
            limit=5,
            since=None,
            until=None,
            timeout_seconds=0.01,
        )
        assert isinstance(sess_out, str)
        assert "GATHER_SESSIONS_TIMEOUT" in sess_out
