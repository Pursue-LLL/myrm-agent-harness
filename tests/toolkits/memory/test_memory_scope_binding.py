from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.scope import (
    apply_channel_affinity,
    bind_scope,
    build_scope,
    derive_namespaces,
    scope_for_write_target,
)
from myrm_agent_harness.toolkits.memory.config import (
    AgentMemoryPolicy,
    MemoryConfig,
    MemoryScopeLevel,
    MemoryWritePolicy,
    RetrievalConfig,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryScope, MemorySearchResult, MemoryType, SemanticMemory


@pytest.mark.asyncio
async def test_manager_scope_initialization():
    config = MemoryConfig(embedding_model="test", retrieval=RetrievalConfig())

    # Test namespaces provided
    manager = MemoryManager(config, user_id="test_user", namespaces=["global", "agent:scifi"])

    assert manager._namespaces == ["global", "agent:scifi"]

    assert manager.scope.primary_namespace == "agent:scifi"
    assert manager.scope.namespaces == ["global", "agent:scifi"]


@pytest.mark.asyncio
async def test_add_knowledge_write_target():
    config = MemoryConfig(embedding_model="test", retrieval=RetrievalConfig())
    manager = MemoryManager(config, user_id="test_user", namespaces=["global", "agent:scifi"])

    with patch(
        "myrm_agent_harness.toolkits.memory.manager.MemoryManager.store", new_callable=AsyncMock
    ) as mock_store:

        async def mock_store_func(x, **kwargs):
            return x

        mock_store.side_effect = mock_store_func

        mem_bound = await manager.add_knowledge("Bound fact")
        assert mem_bound.scope.primary_namespace == "agent:scifi"
        assert mem_bound.scope.namespaces == ["global", "agent:scifi"]

        mem_shared = await manager.add_knowledge("Shared fact", write_target="shared")
        assert mem_shared.scope.primary_namespace == "global"
        assert mem_shared.scope.namespaces == ["global"]


@pytest.mark.asyncio
async def test_add_event_write_target():
    config = MemoryConfig(embedding_model="test", retrieval=RetrievalConfig())
    manager = MemoryManager(config, user_id="test_user", namespaces=["global", "agent:scifi"])

    with patch(
        "myrm_agent_harness.toolkits.memory.manager.MemoryManager.store", new_callable=AsyncMock
    ) as mock_store:

        async def mock_store_func(x, **kwargs):
            return x

        mock_store.side_effect = mock_store_func

        mem_bound = await manager.add_event("Bound event")
        assert mem_bound.scope.primary_namespace == "agent:scifi"
        assert mem_bound.scope.namespaces == ["global", "agent:scifi"]

        mem_shared = await manager.add_event("Shared event", write_target="shared")
        assert mem_shared.scope.primary_namespace == "global"
        assert mem_shared.scope.namespaces == ["global"]


@pytest.mark.asyncio
async def test_add_knowledge_respects_formal_write_policy():
    config = MemoryConfig(embedding_model="test", retrieval=RetrievalConfig())
    manager = MemoryManager(
        config,
        user_id="test_user",
        memory_policy=AgentMemoryPolicy(
            agent_id="planner",
            channel_id="telegram",
            task_id="task-1",
            read_scopes=(MemoryScopeLevel.GLOBAL,),
            write_policy=MemoryWritePolicy.TASK,
        ),
    )

    with patch(
        "myrm_agent_harness.toolkits.memory.manager.MemoryManager.store", new_callable=AsyncMock
    ) as mock_store:

        async def mock_store_func(x, **kwargs):
            return x

        mock_store.side_effect = mock_store_func

        mem_private = await manager.add_knowledge("Task fact")
        mem_shared = await manager.add_knowledge("Shared fact", write_target="shared")

        assert mem_private.scope.primary_namespace == "task:task-1"
        assert mem_private.scope.namespaces == ["task:task-1"]
        assert mem_shared.scope.primary_namespace == "global"
        assert mem_shared.scope.namespaces == ["global"]


def test_bind_scope():
    config = MemoryConfig(embedding_model="test", retrieval=RetrievalConfig())
    manager = MemoryManager(config, user_id="test_user", namespaces=["global", "agent:scifi"])

    # 1. Memory with existing scope namespaces should be preserved
    mem = SemanticMemory(content="Test", importance=0.5)
    mem.scope.namespaces = ["custom:ns"]
    bound = manager._bind_scope(mem)
    assert bound.scope.namespaces == ["custom:ns"]

    # 2. Memory with empty scope namespaces should get the manager's primary scope
    mem_empty = SemanticMemory(content="Test2", importance=0.5)
    mem_empty.scope.namespaces = []
    bound2 = manager._bind_scope(mem_empty)
    assert bound2.scope.primary_namespace == "agent:scifi"
    assert bound2.scope.namespaces == ["global", "agent:scifi"]


def test_scope_helpers_preserve_current_behavior():
    namespaces = derive_namespaces(
        namespaces=None, agent_id="scifi", channel_id="telegram", conversation_id="conv-1", task_id="task-1"
    )
    assert namespaces == [
        "global",
        "agent:scifi",
        "channel:telegram",
        "conversation:conv-1",
        "task:task-1",
    ]

    base_scope = build_scope(
        namespaces=namespaces, agent_id="scifi", channel_id="telegram", conversation_id="conv-1", task_id="task-1"
    )
    private_scope = scope_for_write_target(base_scope, namespaces, "bound")
    shared_scope = scope_for_write_target(base_scope, namespaces, "shared")

    assert private_scope.namespaces == namespaces
    assert shared_scope.primary_namespace == "global"
    assert shared_scope.namespaces == ["global"]


def test_scope_helpers_support_formal_memory_policy():
    policy = AgentMemoryPolicy(
        agent_id="planner",
        channel_id="telegram",
        conversation_id="conv-1",
        task_id="task-1",
        read_scopes=(MemoryScopeLevel.GLOBAL),
        write_policy=MemoryWritePolicy.TASK,
    )
    namespaces = derive_namespaces(
        namespaces=None, agent_id=None, channel_id=None, conversation_id=None, task_id=None, memory_policy=policy
    )

    assert namespaces == ["global"]

    base_scope = build_scope(
        namespaces=namespaces, agent_id=None, channel_id=None, conversation_id=None, task_id=None, memory_policy=policy
    )

    assert base_scope.primary_namespace == "task:task-1"
    assert base_scope.namespaces == ["task:task-1"]
    assert base_scope.agent_id == "planner"
    assert base_scope.channel_id == "telegram"


def test_bind_scope_helper_uses_scope_copy():
    base_scope = MemoryScope(
        primary_namespace="agent:scifi", namespaces=["global", "agent:scifi"], agent_id="scifi", channel_id="telegram"
    )
    memory = SemanticMemory(content="Need binding", importance=0.5)
    memory.scope.namespaces = []

    bound = bind_scope(memory, base_scope)

    assert bound.scope.primary_namespace == "agent:scifi"
    assert bound.scope.namespaces == ["global", "agent:scifi"]
    assert bound.scope.channel_id == "telegram"
    assert bound.scope is not base_scope


def test_apply_channel_affinity_helper_prefers_current_channel():
    current = MemorySearchResult(
        memory=SemanticMemory(
            id="current",
            content="Current",
            importance=0.5,
            scope=MemoryScope(
                primary_namespace="channel:telegram", namespaces=["global", "channel:telegram"], channel_id="telegram"
            ),
        ),
        score=0.8,
        memory_type=MemoryType.SEMANTIC,
    )
    other = MemorySearchResult(
        memory=SemanticMemory(
            id="other",
            content="Other",
            importance=0.5,
            scope=MemoryScope(
                primary_namespace="channel:feishu", namespaces=["global", "channel:feishu"], channel_id="feishu"
            ),
        ),
        score=0.8,
        memory_type=MemoryType.SEMANTIC,
    )

    adjusted = apply_channel_affinity([other, current], current_channel_id="telegram")

    assert adjusted[0].score < adjusted[1].score
