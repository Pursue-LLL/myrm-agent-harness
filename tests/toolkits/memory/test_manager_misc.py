"""Tests for MemoryManager miscellaneous operations."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError, MemoryNotFoundError
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


class TestUpdateMemory:
    """Test update_memory method."""

    @pytest.mark.asyncio
    async def test_update_memory_not_found_raises_error(self, mock_vector_store, mock_embedding, memory_config):
        """Test updating non-existent memory raises error."""
        mock_vector_store.get.return_value = None

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        with pytest.raises(MemoryNotFoundError, match="Memory mem-1 not found"):
            await manager.update_memory("mem-1", content="New content")

    @pytest.mark.asyncio
    async def test_update_procedural_memory(self, mock_relational_store, memory_config):
        """Test updating a procedural rule."""
        existing_rule = ProceduralMemory(id="rule-1", content="Old rule", trigger="old trigger", action="old action")
        updated_rule = ProceduralMemory(id="rule-1", content="New rule", trigger="old trigger", action="old action")
        mock_relational_store.get_rule.return_value = existing_rule
        mock_relational_store.update_rule.return_value = updated_rule

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.update_memory("rule-1", content="New rule")

        assert result.content == "New rule"
        mock_relational_store.update_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_memory_with_tags(self, mock_vector_store, mock_embedding, memory_config):
        """Test updating memory with tags parameter."""
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
                "tags": "old,tags",
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [existing_doc]
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.update_memory("mem-1", tags=["new", "tags"])

        assert result is not None
        assert result.tags == ["new", "tags"]

    @pytest.mark.asyncio
    async def test_update_memory_with_metadata(self, mock_vector_store, mock_embedding, memory_config):
        """Test updating memory with metadata parameter."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        existing_doc = VectorDocument(
            id="mem-1",
            content="Content",
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

        result = await manager.update_memory("mem-1", metadata={"custom_key": "custom_value"})

        assert result is not None
        assert result.metadata.get("custom_key") == "custom_value"


class TestSetProfileAttribute:
    """Test set_profile_attribute with approval workflow."""

    @pytest.mark.asyncio
    async def test_set_profile_attribute_with_approval(self, mock_relational_store, memory_config):
        """Test set_profile_attribute with approval required returns pending_id."""
        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True)

        pending_id = await manager.set_profile_attribute("timezone", "UTC+8")

        assert pending_id == "pending-1"
        mock_relational_store.submit_pending.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_profile_attribute_duplicate_pending(self, mock_relational_store, memory_config):
        """Test set_profile_attribute with duplicate pending returns empty."""
        mock_relational_store.pending_exists.return_value = True

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True)

        pending_id = await manager.set_profile_attribute("timezone", "UTC+8")

        assert pending_id == ""


class TestCloseMethod:
    """Test close method."""

    @pytest.mark.asyncio
    async def test_close_all_backends(self, mock_vector_store, mock_relational_store, mock_embedding, memory_config):
        """Test close method closes all backends."""
        mock_graph = AsyncMock()
        mock_graph.close = AsyncMock()

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            graph=mock_graph,
        )

        await manager.close()

        mock_relational_store.close.assert_called_once()
        mock_vector_store.close.assert_called_once()
        mock_graph.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_backends(self, memory_config):
        """Test close method when no backends are configured."""
        manager = MemoryManager(memory_config, user_id="test_user")

        await manager.close()


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_store_unknown_memory_type_raises_error(self, mock_vector_store, mock_embedding, memory_config):
        """Test storing unknown memory type raises ValueError."""

        class UnknownMemory:
            user_id = "local"

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        with pytest.raises(ValueError, match="Unknown memory type"):
            await manager.store(UnknownMemory())  # type: ignore

    @pytest.mark.asyncio
    async def test_store_batch_unknown_type_raises_error(self, mock_vector_store, mock_embedding, memory_config):
        """Test store_batch with unknown type raises ValueError."""

        class UnknownMemory:
            user_id = "local"

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        with pytest.raises(ValueError, match="Unknown memory type"):
            await manager.store_batch([UnknownMemory()])  # type: ignore

    def test_active_session_property(self, mock_vector_store, mock_embedding, memory_config):
        """Test active_session property returns correct value."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        assert manager.active_session is None

        session = manager.begin_session("chat-1")
        assert manager.active_session == session

    @pytest.mark.asyncio
    async def test_vec_accessor_raises_without_backends(self, memory_config):
        """Test _vec() raises error when backends not configured."""
        manager = MemoryManager(memory_config, user_id="test_user")

        with pytest.raises(MemoryError, match="Vector \\+ Embedding backends required"):
            manager._vec()

    @pytest.mark.asyncio
    async def test_rel_accessor_raises_without_backend(self, memory_config):
        """Test _rel() raises error when backend not configured."""
        manager = MemoryManager(memory_config, user_id="test_user")

        with pytest.raises(MemoryError, match="Relational backend required"):
            manager._rel()

    @pytest.mark.asyncio
    async def test_delete_memory_without_vector_raises_error(self, memory_config):
        """Test delete_memory raises error when vector backend not configured."""
        manager = MemoryManager(memory_config, user_id="test_user")

        with pytest.raises(MemoryError, match="Vector backend is required"):
            await manager.delete_memory("collection", ["mem-1"])
