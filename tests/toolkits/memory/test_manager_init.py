"""Tests for MemoryManager initialization and properties."""

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError
from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy, MemoryScopeLevel, MemoryWritePolicy
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType


class TestMemoryManagerInitialization:
    """Test MemoryManager initialization and properties."""

    def test_init_with_approval_requires_relational(self, mock_vector_store, mock_embedding, memory_config):
        """Test that approval_required=True requires relational backend."""
        with pytest.raises(MemoryError, match="approval_required=True requires a relational backend"):
            MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, approval_required=True
            )

    def test_init_with_dedup_llm(self, mock_vector_store, mock_embedding, memory_config):
        """Test initialization with dedup_llm creates deduplicator."""
        mock_llm = MagicMock()
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, dedup_llm=mock_llm
        )

        assert manager._deduplicator is not None

    def test_init_deduplicator_handles_exception(self, mock_vector_store, mock_embedding, memory_config):
        """Test that deduplicator initialization exception is handled gracefully."""
        mock_llm = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.memory.strategies.deduplicator.SmartDeduplicator",
            side_effect=Exception("Init failed"),
        ):
            manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, dedup_llm=mock_llm
            )

            assert manager._deduplicator is None

    def test_properties_access(self, mock_vector_store, mock_relational_store, mock_embedding, memory_config):
        """Test all property accessors."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        assert manager.user_id == "test_user"
        assert manager.config == memory_config
        assert manager.has_relational is True
        assert manager.has_vector is True
        assert manager.has_graph is False
        assert manager.approval_required is True

    def test_scope_and_namespaces_are_derived(self, mock_vector_store, mock_embedding, memory_config):
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            agent_id="planner",
            channel_id="telegram",
            conversation_id="conv-1",
            task_id="task-1",
        )

        assert manager.namespaces == [
            "global",
            "agent:planner",
            "channel:telegram",
            "conversation:conv-1",
            "task:task-1",
        ]
        assert manager.scope.primary_namespace == "task:task-1"
        assert manager.scope.channel_id == "telegram"

    def test_memory_policy_formalizes_read_write_boundaries(self, mock_vector_store, mock_embedding, memory_config):
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            memory_policy=AgentMemoryPolicy(
                agent_id="planner",
                channel_id="telegram",
                conversation_id="conv-1",
                task_id="task-1",
                read_scopes=(MemoryScopeLevel.GLOBAL, MemoryScopeLevel.AGENT),
                write_policy=MemoryWritePolicy.TASK,
            ),
        )

        assert manager.namespaces == [
            "global",
            "agent:planner",
        ]
        assert manager.memory_policy is not None
        assert manager.memory_policy.write_policy == MemoryWritePolicy.TASK
        assert manager.scope.primary_namespace == "task:task-1"
        assert manager.scope.namespaces == ["task:task-1"]
        assert manager.scope.agent_id == "planner"

    def test_memory_policy_requires_matching_write_scope_identifier(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        with pytest.raises(ValueError, match="requires a matching scope ID"):
            MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
                embedding=mock_embedding,
                memory_policy=AgentMemoryPolicy(agent_id="planner", write_policy=MemoryWritePolicy.TASK),
            )

    def test_get_enabled_types_all_backends(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test get_enabled_types with all backends."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        enabled = manager.get_enabled_types()
        assert MemoryType.PROFILE in enabled
        assert MemoryType.PROCEDURAL in enabled
        assert MemoryType.SEMANTIC in enabled
        assert MemoryType.EPISODIC in enabled

    def test_get_enabled_types_vector_only(self, mock_vector_store, mock_embedding, memory_config):
        """Test get_enabled_types with only vector backend."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        enabled = manager.get_enabled_types()
        assert MemoryType.SEMANTIC in enabled
        assert MemoryType.EPISODIC in enabled
        assert MemoryType.PROFILE not in enabled
        assert MemoryType.PROCEDURAL not in enabled

    def test_get_enabled_types_relational_only(self, mock_relational_store, memory_config):
        """Test get_enabled_types with only relational backend."""
        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        enabled = manager.get_enabled_types()
        assert MemoryType.PROFILE in enabled
        assert MemoryType.PROCEDURAL in enabled
        assert MemoryType.SEMANTIC not in enabled
        assert MemoryType.EPISODIC not in enabled
