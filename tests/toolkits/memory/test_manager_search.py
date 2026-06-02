"""Tests for MemoryManager search operations covering all memory types."""

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy, MemoryScopeLevel, MemoryWritePolicy
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


class TestSearchOperations:
    """Test search method with different memory types."""

    @pytest.mark.asyncio
    async def test_search_with_procedural_type(self, mock_relational_store, memory_config):
        """Test search with PROCEDURAL memory type only."""
        rule1 = ProceduralMemory(
            id="rule-1",
            content="When user asks about weather, call weather API",
            trigger="weather",
            action="call_weather_api",
        )
        rule2 = ProceduralMemory(
            id="rule-2", content="When user asks about time, return current time", trigger="time", action="return_time"
        )
        mock_relational_store.search_rules.return_value = [rule1, rule2]

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        results = await manager.search("weather", memory_types=[MemoryType.PROCEDURAL], limit=10)

        assert len(results) == 2
        assert all(r.memory_type == MemoryType.PROCEDURAL for r in results)
        assert isinstance(results[0].memory, ProceduralMemory)
        mock_relational_store.search_rules.assert_called_once_with(
            "weather", limit=10, namespaces=["global", "agent:default"]
        )

    @pytest.mark.asyncio
    async def test_search_with_profile_type(self, mock_relational_store, memory_config):
        """Test search with PROFILE memory type only."""
        from myrm_agent_harness.toolkits.memory.types import ProfileEntry

        mock_relational_store.list_profiles.return_value = [
            ProfileEntry(key="timezone", value="UTC+8"),
            ProfileEntry(key="language", value="zh-CN"),
        ]

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        results = await manager.search("timezone", memory_types=[MemoryType.PROFILE], limit=10)

        assert len(results) == 1
        assert results[0].memory_type == MemoryType.PROFILE
        assert "timezone" in results[0].memory.content
        mock_relational_store.list_profiles.assert_called_once_with(namespaces=["global", "agent:default"])

    @pytest.mark.asyncio
    async def test_search_prefers_current_channel_results(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult

        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 2
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="mem-other",
                    content="Cross-channel memory",
                    vector=[0.1] * 768,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "access_count": 0,
                        "channel_id": "feishu",
                        "namespaces": ["global", "channel:feishu"],
                        "primary_namespace": "channel:feishu",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.8,
            ),
            VectorSearchResult(
                document=VectorDocument(
                    id="mem-current",
                    content="Current-channel memory",
                    vector=[0.1] * 768,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "access_count": 0,
                        "channel_id": "telegram",
                        "namespaces": ["global", "channel:telegram"],
                        "primary_namespace": "channel:telegram",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.8,
            ),
        ]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, channel_id="telegram"
        )

        results = await manager.search("memory", memory_types=[MemoryType.SEMANTIC], limit=5, use_rrf=False)

        assert results[0].id == "mem-current"

    @pytest.mark.asyncio
    async def test_search_without_vector_backend_returns_empty(self, mock_relational_store, memory_config):
        """Test search returns empty results when requesting vector types without vector backend."""
        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        results = await manager.search("test query", memory_types=[MemoryType.SEMANTIC])
        assert results == []

    @pytest.mark.asyncio
    async def test_search_semantic_passes_namespaces(self, mock_vector_store, mock_embedding, memory_config):
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="mem-1",
                    content="Scoped semantic",
                    vector=[0.1] * 768,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "access_count": 0,
                        "namespaces": ["global", "channel:telegram"],
                        "primary_namespace": "channel:telegram",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.9,
            )
        ]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, channel_id="telegram"
        )

        await manager.search("scoped", memory_types=[MemoryType.SEMANTIC], limit=5)

        assert mock_vector_store.search.call_args.kwargs["filters"]["namespaces"] == manager.namespaces

    @pytest.mark.asyncio
    async def test_search_semantic_uses_policy_read_namespaces(self, mock_vector_store, mock_embedding, memory_config):
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = []

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            memory_policy=AgentMemoryPolicy(
                agent_id="planner",
                channel_id="telegram",
                task_id="task-1",
                read_scopes=(MemoryScopeLevel.GLOBAL, MemoryScopeLevel.AGENT),
                write_policy=MemoryWritePolicy.TASK,
            ),
        )

        await manager.search("scoped", memory_types=[MemoryType.SEMANTIC], limit=5)

        assert mock_vector_store.search.call_args.kwargs["filters"]["namespaces"] == [
            "global",
            "agent:planner",
        ]

    @pytest.mark.asyncio
    async def test_search_includes_claim_graph_results(
        self, mock_vector_store, mock_embedding, mock_graph_store, memory_config
    ):
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="mem-1",
                    content="JWT auth implementation details",
                    vector=[0.1] * 768,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "access_count": 0,
                        "namespaces": ["global", "channel:telegram"],
                        "primary_namespace": "channel:telegram",
                        "channel_id": "telegram",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.7,
            )
        ]
        mock_vector_store.get.return_value = []
        mock_graph_store.find_nodes.return_value = [
            GraphNode(
                id="claim:auth-task",
                labels=["Claim"],
                properties={
                    "primary_namespace": "channel:telegram",
                    "scope_namespaces_json": "global|channel:telegram",
                    "scope_level": "channel",
                    "channel_id": "telegram",
                    "claim_key": "auth-task",
                    "title": "Auth task",
                    "claim_text": "Add JWT authentication -> Completed implementation",
                    "confidence": 0.91,
                    "freshness_days": 1,
                    "freshness": "fresh",
                    "contradiction_status": "none",
                    "evidence_count": 3,
                    "last_result": "Completed implementation",
                    "latest_channel_id": "telegram",
                },
            )
        ]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            channel_id="telegram",
            auto_warmup=False,
        )

        results = await manager.search("jwt auth", memory_types=[MemoryType.SEMANTIC], limit=5, use_rrf=False)

        assert any(result.id == "claim:auth-task" for result in results)
        claim_result = next(result for result in results if result.id == "claim:auth-task")
        assert isinstance(claim_result.memory, ClaimMemory)
        assert claim_result.memory_type == MemoryType.CLAIM
        assert claim_result.memory.claim_key == "auth-task"
        assert claim_result.memory.content.startswith("Claim: Auth task")
        assert claim_result.memory.scope.channel_id == "telegram"
        assert claim_result.memory.scope.primary_namespace == "channel:telegram"
        assert mock_graph_store.find_nodes.await_count == 1

    @pytest.mark.asyncio
    async def test_search_claim_type_works_without_vector_hits(
        self, mock_vector_store, mock_embedding, mock_graph_store, memory_config
    ):
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 0
        mock_vector_store.search.return_value = []
        mock_graph_store.find_nodes.return_value = [
            GraphNode(
                id="claim:deploy-policy",
                labels=["Claim"],
                properties={
                    "primary_namespace": "global",
                    "scope_namespaces_json": "global",
                    "scope_level": "global",
                    "claim_key": "deploy-policy",
                    "title": "Deploy policy",
                    "claim_text": "Use canary rollout before full release",
                    "confidence": 0.87,
                    "freshness_days": 2,
                    "freshness": "fresh",
                    "contradiction_status": "none",
                    "evidence_count": 2,
                    "last_result": "Canary rollout adopted",
                    "latest_channel_id": "telegram",
                    "last_evidence_at": datetime.now(UTC).isoformat(),
                },
            )
        ]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            channel_id="telegram",
            auto_warmup=False,
        )

        results = await manager.search("canary rollout", memory_types=[MemoryType.CLAIM], limit=5, use_rrf=False)

        assert len(results) == 1
        assert isinstance(results[0].memory, ClaimMemory)
        assert results[0].memory_type == MemoryType.CLAIM
        assert results[0].memory.title == "Deploy policy"

    @pytest.mark.asyncio
    async def test_search_claim_graph_filters_out_mismatched_scope(
        self, mock_vector_store, mock_embedding, mock_graph_store, memory_config
    ):
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 0
        mock_vector_store.search.return_value = []
        mock_graph_store.find_nodes.return_value = [
            GraphNode(
                id="claim:task-test_user-other:deploy-policy",
                labels=["Claim"],
                properties={
                    "primary_namespace": "task:other",
                    "scope_namespaces_json": "global|task:other",
                    "scope_level": "task",
                    "task_id": "other",
                    "claim_key": "deploy-policy",
                    "title": "Deploy policy",
                    "claim_text": "Use canary rollout before full release",
                    "confidence": 0.87,
                    "freshness_days": 2,
                    "freshness": "fresh",
                    "contradiction_status": "none",
                    "evidence_count": 2,
                    "last_result": "Canary rollout adopted",
                    "latest_channel_id": "telegram",
                    "last_evidence_at": datetime.now(UTC).isoformat(),
                },
            )
        ]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            channel_id="telegram",
            auto_warmup=False,
        )

        results = await manager.search("canary rollout", memory_types=[MemoryType.CLAIM], limit=5, use_rrf=False)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_hides_internal_task_digest_from_recall(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="digest-1",
                    content="**Title**: Auth task",
                    vector=[0.1] * 768,
                    metadata={
                        "memory_type": "episodic",
                        "event_type": "task_digest",
                        "importance": 0.9,
                        "confidence": 0.9,
                        "access_count": 0,
                        "namespaces": ["global", "channel:telegram"],
                        "primary_namespace": "channel:telegram",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.95,
            )
        ]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False
        )

        results = await manager.search("auth task", memory_types=[MemoryType.EPISODIC], limit=5, use_rrf=False)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_hides_archive_checkpoint_from_recall(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="archive-1",
                    content="Archive checkpoint (tool=grep_tool, path=.context/chat/compacted/out.txt):\nQ3 -12%",
                    vector=[0.1] * 768,
                    metadata={
                        "memory_type": "episodic",
                        "event_type": "archive_checkpoint",
                        "importance": 0.85,
                        "access_count": 0,
                        "namespaces": ["global", "conversation:chat-1"],
                        "primary_namespace": "conversation:chat-1",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                score=0.95,
            )
        ]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search("Q3 revenue", memory_types=[MemoryType.EPISODIC], limit=5, use_rrf=False)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_mixed_types_uses_rrf(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test search with mixed types uses RRF fusion."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult

        mock_embedding.embed.return_value = [0.1] * 768

        doc = VectorDocument(
            id="mem-1",
            content="Test semantic",
            vector=[0.1] * 768,
            metadata={
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "source_chat_id": "",
                "preference_type": "",
                "preference_strength": 0.0,
                "correction_of": "",
                "access_count": 0,
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.search.return_value = [VectorSearchResult(document=doc, score=0.9)]
        mock_vector_store.count.return_value = 100
        mock_vector_store.scroll.return_value = []

        rule = ProceduralMemory(id="rule-1", content="Test rule", trigger="trigger", action="action")
        mock_relational_store.search_rules.return_value = [rule]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        results = await manager.search(
            "test query", memory_types=[MemoryType.SEMANTIC, MemoryType.PROCEDURAL], limit=10, use_rrf=True
        )

        assert isinstance(results, list)
        mock_relational_store.search_rules.assert_called_once()
        mock_vector_store.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_without_rrf_simple_merge(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test search without RRF uses simple merge and rank."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult

        mock_embedding.embed.return_value = [0.1] * 768

        doc = VectorDocument(
            id="mem-1",
            content="Test semantic",
            vector=[0.1] * 768,
            metadata={
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "source_chat_id": "",
                "preference_type": "",
                "preference_strength": 0.0,
                "correction_of": "",
                "access_count": 0,
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.search.return_value = [VectorSearchResult(document=doc, score=0.9)]
        mock_vector_store.count.return_value = 100
        mock_vector_store.scroll.return_value = []
        mock_relational_store.search_rules.return_value = []

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        results = await manager.search(
            "test query", memory_types=[MemoryType.SEMANTIC, MemoryType.PROCEDURAL], limit=10, use_rrf=False
        )

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_with_graph_enrichment(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test search enriches results with graph when available."""
        from unittest.mock import AsyncMock, patch

        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult

        mock_embedding.embed.return_value = [0.1] * 768

        doc = VectorDocument(
            id="mem-1",
            content="Test semantic",
            vector=[0.1] * 768,
            metadata={
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "source_chat_id": "",
                "preference_type": "",
                "preference_strength": 0.0,
                "correction_of": "",
                "access_count": 0,
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.search.return_value = [VectorSearchResult(document=doc, score=0.9)]
        mock_vector_store.count.return_value = 100
        mock_vector_store.scroll.return_value = []

        mock_graph = AsyncMock()

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            graph=mock_graph,
        )

        with patch(
            "myrm_agent_harness.toolkits.memory._internal.search_service.enrich_with_graph", new_callable=AsyncMock
        ) as mock_enrich:
            mock_enrich.return_value = [
                MemorySearchResult(
                    memory=SemanticMemory(content="Enriched result"), score=0.9, memory_type=MemoryType.SEMANTIC
                )
            ]

            results = await manager.search("test query", memory_types=[MemoryType.SEMANTIC], limit=10)

            mock_enrich.assert_called_once()
            assert len(results) > 0
