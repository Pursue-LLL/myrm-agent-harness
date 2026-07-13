from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


@pytest.mark.asyncio
async def test_update_procedural_memory_reasoning_application():
    mock_rel = AsyncMock()
    config = MemoryConfig(embedding_model="test")
    manager = MemoryManager(config, user_id="test_user", relational=mock_rel)

    existing = ProceduralMemory(
        id="mem-1",
        content="abc",
        trigger="t",
        action="a",
        source="agent_self"
    )

    mock_rel.get_rule.return_value = existing
    mock_rel.update_rule.return_value = existing

    updated = await manager.update_memory(
        "mem-1",
        reasoning="new reasoning",
        application="new app"
    )

    mock_rel.update_rule.assert_awaited_once()
    called_mem = mock_rel.update_rule.call_args[0][1]
    assert called_mem.reasoning == "new reasoning"
    assert called_mem.application == "new app"

@pytest.mark.asyncio
async def test_get_tool_rules_success():
    mock_rel = AsyncMock()
    config = MemoryConfig(embedding_model="test")
    manager = MemoryManager(config, user_id="test_user", relational=mock_rel)

    expected = [ProceduralMemory(id="m1", content="abc", trigger="t", action="a", source="agent_self")]
    mock_rel.list_rules_by_tool.return_value = expected

    rules = await manager.get_tool_rules("my_tool")
    assert rules == expected
    mock_rel.list_rules_by_tool.assert_awaited_once_with("my_tool", active_only=True, limit=30, namespaces=manager._namespaces)
