"""Tests for framework-level shared namespace memory semantics."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import search_semantic
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import AnyMemory


@pytest.fixture
def memory_config() -> MemoryConfig:
    return MemoryConfig(embedding_model="test-model")


@pytest.mark.asyncio
async def test_write_target_shared_uses_shared_namespace(memory_config: MemoryConfig) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        namespaces=["shared:customer-a", "agent:writer"],
    )

    with patch("myrm_agent_harness.toolkits.memory.manager.MemoryManager.store", new_callable=AsyncMock) as store:

        async def store_memory(memory: AnyMemory, **_kwargs: object) -> AnyMemory:
            return memory

        store.side_effect = store_memory

        memory = await manager.add_knowledge("Customer A prefers concise weekly reports", write_target="shared")

    assert memory.scope.primary_namespace == "shared:customer-a"
    assert memory.scope.namespaces == ["shared:customer-a"]


@pytest.mark.asyncio
async def test_write_target_shared_prefers_bound_shared_namespace(memory_config: MemoryConfig) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        namespaces=["global", "agent:writer", "shared:customer-a"],
    )

    with patch("myrm_agent_harness.toolkits.memory.manager.MemoryManager.store", new_callable=AsyncMock) as store:

        async def store_memory(memory: AnyMemory, **_kwargs: object) -> AnyMemory:
            return memory

        store.side_effect = store_memory

        memory = await manager.add_knowledge("Customer A prefers concise weekly reports", write_target="shared")

    assert memory.scope.primary_namespace == "shared:customer-a"
    assert memory.scope.namespaces == ["shared:customer-a"]


@pytest.mark.asyncio
async def test_write_target_bound_keeps_full_manager_scope(memory_config: MemoryConfig) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        namespaces=["shared:customer-a", "agent:writer"],
    )

    with patch("myrm_agent_harness.toolkits.memory.manager.MemoryManager.store", new_callable=AsyncMock) as store:

        async def store_memory(memory: AnyMemory, **_kwargs: object) -> AnyMemory:
            return memory

        store.side_effect = store_memory

        memory = await manager.add_event("Drafted the report outline")

    assert memory.scope.primary_namespace == "agent:writer"
    assert memory.scope.namespaces == ["shared:customer-a", "agent:writer"]


@pytest.mark.asyncio
async def test_bound_write_primary_namespace_ignores_appended_shared_context(memory_config: MemoryConfig) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        namespaces=["global", "agent:writer", "shared:customer-a"],
    )

    with patch("myrm_agent_harness.toolkits.memory.manager.MemoryManager.store", new_callable=AsyncMock) as store:

        async def store_memory(memory: AnyMemory, **_kwargs: object) -> AnyMemory:
            return memory

        store.side_effect = store_memory

        memory = await manager.add_event("Drafted the report outline")

    assert memory.scope.primary_namespace == "agent:writer"
    assert memory.scope.namespaces == ["global", "agent:writer", "shared:customer-a"]


@pytest.mark.asyncio
async def test_search_semantic_uses_namespace_filter(memory_config: MemoryConfig) -> None:
    vector = AsyncMock()
    vector.count.return_value = 0
    vector.search.return_value = []

    await search_semantic(
        [0.1, 0.2],
        limit=5,
        vector=vector,
        config=memory_config,
        namespaces=["shared:customer-a", "agent:writer"],
    )

    filters = vector.search.call_args.kwargs["filters"]
    assert filters == {"archived": False, "namespaces": ["shared:customer-a", "agent:writer"]}


def test_manager_exposes_no_team_sharing_api(memory_config: MemoryConfig) -> None:
    manager = MemoryManager(memory_config, user_id="test_user")

    assert not hasattr(manager, "team_id")
    assert not hasattr(manager, "share_memory")
    assert not hasattr(manager, "unshare_memory")
    assert not hasattr(manager, "list_team_memories")


def test_invalid_namespace_is_rejected(memory_config: MemoryConfig) -> None:
    with pytest.raises(ValueError, match="Invalid memory namespace"):
        MemoryManager(memory_config, user_id="test_user", namespaces=["invalid namespace"])
