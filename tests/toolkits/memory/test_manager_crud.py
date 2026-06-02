"""Tests for MemoryManager CRUD operations."""

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType, ProceduralMemory, ProfileEntry, SemanticMemory


class TestGetOperations:
    """Test get and retrieval operations."""

    @pytest.mark.asyncio
    async def test_get_semantic_memory(self, mock_vector_store, mock_embedding, memory_config):
        """Test getting a semantic memory by ID."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

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
        mock_vector_store.get.return_value = [doc]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.get_memory("mem-1")

        assert result is not None
        assert isinstance(result, SemanticMemory)
        assert result.id == "mem-1"

    @pytest.mark.asyncio
    async def test_get_profile_attribute(self, mock_relational_store, memory_config):
        """Test getting a profile attribute."""
        mock_relational_store.get_profile.return_value = "UTC+8"

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.get_profile_attribute("timezone")

        assert result == "UTC+8"
        mock_relational_store.get_profile.assert_called_once_with(
            "timezone", namespaces=["global", "agent:default"]
        )

    @pytest.mark.asyncio
    async def test_get_procedural_rule(self, mock_relational_store, memory_config):
        """Test getting a procedural rule."""
        rule = ProceduralMemory(id="rule-1", content="Test rule", trigger="trigger", action="action")
        mock_relational_store.get_rule.return_value = rule

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.get_memory("rule-1")

        assert result == rule

    @pytest.mark.asyncio
    async def test_get_memory_with_exception_logs_warning(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test get_memory logs warning when backend raises exception."""
        mock_vector_store.get.side_effect = Exception("Database error")

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        result = await manager.get_memory("mem-1")
        assert result is None


class TestListAndCountOperations:
    """Test list and count operations."""

    @pytest.mark.asyncio
    async def test_list_by_type_semantic(self, mock_vector_store, mock_embedding, memory_config):
        """Test listing semantic memories."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        docs = [
            VectorDocument(
                id=f"mem-{i}",
                content=f"Memory {i}",
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
            for i in range(5)
        ]
        mock_vector_store.scroll.return_value = docs

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.list_memories(MemoryType.SEMANTIC, limit=10)

        assert len(result) == 5
        assert all(isinstance(m, SemanticMemory) for m in result)

    @pytest.mark.asyncio
    async def test_list_by_type_profile(self, mock_relational_store, memory_config):
        """Test listing profile memories converts structured entries."""
        mock_relational_store.list_profiles.return_value = [
            ProfileEntry(key="timezone", value="UTC+8"),
        ]

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.list_memories(MemoryType.PROFILE, limit=10)

        assert len(result) == 1
        assert isinstance(result[0], SemanticMemory)
        assert result[0].content == "timezone: UTC+8"
        assert result[0].metadata["key"] == "timezone"
        assert result[0].metadata["value"] == "UTC+8"
        mock_relational_store.list_profiles.assert_called_once_with(limit=10, offset=0, namespaces=["global", "agent:default"])

    @pytest.mark.asyncio
    async def test_count_by_type(self, mock_vector_store, mock_embedding, memory_config):
        """Test counting memories by type."""
        mock_vector_store.count.return_value = 42

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        count = await manager.count_memories(MemoryType.SEMANTIC)

        assert count == 42


class TestUpdateOperations:
    """Test update operations."""

    @pytest.mark.asyncio
    async def test_update_semantic_memory(self, mock_vector_store, mock_embedding, memory_config):
        """Test updating a semantic memory."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        existing_doc = VectorDocument(
            id="mem-1",
            content="Old content",
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
        mock_vector_store.get.return_value = [existing_doc]
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.update_memory("mem-1", content="Updated content", importance=0.8)

        assert result is not None
        assert result.content == "Updated content"
        assert result.metadata.get("previous_content") == "Old content"
        mock_vector_store.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_without_content_no_previous(self, mock_vector_store, mock_embedding, memory_config):
        """Updating without content change should not set previous_content."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        existing_doc = VectorDocument(
            id="mem-1",
            content="Original content",
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
        mock_vector_store.get.return_value = [existing_doc]
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.update_memory("mem-1", importance=0.9)

        assert result.content == "Original content"
        assert "previous_content" not in result.metadata

    @pytest.mark.asyncio
    async def test_set_profile_attribute(self, mock_relational_store, memory_config):
        """Test setting a profile attribute."""
        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.set_profile_attribute("language", "zh-CN")
        assert result is None
        scope = mock_relational_store.set_profile.await_args.kwargs["scope"]
        assert scope.primary_namespace == "agent:default"
        assert scope.namespaces == ["global", "agent:default"]
        mock_relational_store.set_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_semantic_persists_scope_metadata(self, mock_vector_store, mock_embedding, memory_config):
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            agent_id="assistant",
            channel_id="telegram",
            conversation_id="conv-1",
        )

        memory = SemanticMemory(content="Remember this scoped fact")
        await manager.store(memory)

        stored_doc = mock_vector_store.upsert.call_args.args[1][0]
        assert stored_doc.metadata["primary_namespace"] == "conversation:conv-1"
        assert stored_doc.metadata["namespaces"] == [
            "global",
            "agent:assistant",
            "channel:telegram",
            "conversation:conv-1",
        ]


class TestDeleteOperations:
    """Test delete operations."""

    @pytest.mark.asyncio
    async def test_delete_memory(self, mock_vector_store, mock_embedding, memory_config):
        """Test deleting memories by collection and IDs."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        mock_vector_store.get.return_value = [
            VectorDocument(id=mid, content="c", vector=[], metadata={"user_id": "test_user"}) for mid in ("mem-1", "mem-2")
        ]
        mock_vector_store.delete.return_value = 2

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        count = await manager.delete_memory("test_collection", ["mem-1", "mem-2"])

        assert count == 2
        mock_vector_store.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_profile_entry(self, mock_relational_store, memory_config):
        """Test deleting a profile entry."""
        mock_relational_store.delete_profile.return_value = True

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.delete_profile("timezone")

        assert result is True
        mock_relational_store.delete_profile.assert_called_once_with(
            "timezone", namespaces=["global", "agent:default"]
        )

    @pytest.mark.asyncio
    async def test_delete_by_type(self, mock_vector_store, mock_embedding, memory_config):
        """Test deleting all memories of a specific type."""
        mock_vector_store.delete_by_filter.return_value = 10

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        count = await manager.delete_by_type(MemoryType.SEMANTIC)

        assert count == 10

    @pytest.mark.asyncio
    async def test_delete_rule(self, mock_relational_store, memory_config):
        """Test deleting a procedural rule."""
        mock_relational_store.delete_rule.return_value = True

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.delete_rule("rule-1")

        assert result is True
        mock_relational_store.delete_rule.assert_called_once_with("rule-1")

    @pytest.mark.asyncio
    async def test_delete_all(self, mock_vector_store, mock_relational_store, mock_embedding, memory_config):
        """Test deleting all memories for a user."""
        mock_relational_store.delete_all.return_value = 5
        mock_vector_store.delete_by_filter.return_value = 10

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        counts = await manager.delete_all()

        assert "relational" in counts
        assert counts["relational"] == 5
        mock_vector_store.delete_by_filter.assert_called()

    @pytest.mark.asyncio
    async def test_delete_all_handles_relational_exception(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test delete_all handles relational backend exceptions gracefully."""
        mock_relational_store.delete_all.side_effect = Exception("DB connection failed")
        mock_vector_store.delete_by_filter.return_value = 10

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        counts = await manager.delete_all()

        assert "relational" not in counts or counts.get("relational") is None

    @pytest.mark.asyncio
    async def test_delete_all_handles_vector_exception(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test delete_all handles vector backend exceptions gracefully."""
        mock_relational_store.delete_all.return_value = 5
        mock_vector_store.delete_by_filter.side_effect = Exception("Vector delete failed")

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        counts = await manager.delete_all()

        assert counts.get("relational") == 5

    @pytest.mark.asyncio
    async def test_get_memory_with_exception_logs_warning(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test get_memory logs warning when backend raises exception."""
        mock_vector_store.get.side_effect = Exception("Database error")

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        result = await manager.get_memory("mem-1")
        assert result is None


class TestGraphCascadeDelete:
    """Test graph cascade deletion on memory removal."""

    @pytest.mark.asyncio
    async def test_delete_memory_cascades_to_graph(
        self, mock_vector_store, mock_graph_store, mock_embedding, memory_config
    ):
        """delete_memory cleans up graph subgraph for each deleted memory."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        mock_vector_store.get.return_value = [
            VectorDocument(id=mid, content="c", vector=[], metadata={"user_id": "test_user"}) for mid in ("mem-1", "mem-2")
        ]
        mock_vector_store.delete.return_value = 2

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, graph=mock_graph_store
        )

        count = await manager.delete_memory("test_collection", ["mem-1", "mem-2"])

        assert count == 2
        assert mock_graph_store.delete_subgraph.call_count == 2
        mock_graph_store.delete_subgraph.assert_any_call("mem-1")
        mock_graph_store.delete_subgraph.assert_any_call("mem-2")

    @pytest.mark.asyncio
    async def test_delete_memory_without_graph_backend(self, mock_vector_store, mock_embedding, memory_config):
        """delete_memory works normally when no graph backend is present."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        mock_vector_store.get.return_value = [
            VectorDocument(id="mem-1", content="c", vector=[], metadata={"user_id": "test_user"}),
        ]
        mock_vector_store.delete.return_value = 1

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        count = await manager.delete_memory("test_collection", ["mem-1"])

        assert count == 1

    @pytest.mark.asyncio
    async def test_delete_memory_graph_error_is_non_fatal(
        self, mock_vector_store, mock_graph_store, mock_embedding, memory_config
    ):
        """Graph cleanup failure does not prevent vector deletion from succeeding."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        mock_vector_store.get.return_value = [
            VectorDocument(id="mem-1", content="c", vector=[], metadata={"user_id": "test_user"}),
        ]
        mock_vector_store.delete.return_value = 1
        mock_graph_store.delete_subgraph.side_effect = Exception("Graph error")

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, graph=mock_graph_store
        )

        count = await manager.delete_memory("test_collection", ["mem-1"])

        assert count == 1

    @pytest.mark.asyncio
    async def test_delete_all_includes_graph_cleanup(
        self, mock_vector_store, mock_relational_store, mock_graph_store, mock_embedding, memory_config
    ):
        """delete_all cleans up graph data in addition to relational and vector."""
        mock_relational_store.delete_all.return_value = 5
        mock_vector_store.delete_by_filter.return_value = 10
        mock_graph_store.delete_all_by_owner.return_value = 8

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
        )

        counts = await manager.delete_all()

        assert counts["graph"] == 8
        mock_graph_store.delete_all_by_owner.assert_called_once_with("test_user")

    @pytest.mark.asyncio
    async def test_delete_all_graph_error_is_non_fatal(
        self, mock_vector_store, mock_relational_store, mock_graph_store, mock_embedding, memory_config
    ):
        """delete_all handles graph cleanup failures gracefully."""
        mock_relational_store.delete_all.return_value = 5
        mock_vector_store.delete_by_filter.return_value = 10
        mock_graph_store.delete_all_by_owner.side_effect = Exception("Graph error")

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
        )

        counts = await manager.delete_all()

        assert counts.get("relational") == 5
        assert "graph" not in counts
