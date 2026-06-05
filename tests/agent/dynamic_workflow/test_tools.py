import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.tools import SpawnSubagentTool
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        store = WorkflowEventStore(db_path)
        yield store

@pytest.mark.asyncio
async def test_spawn_tool_cache_hit(temp_store):
    temp_store.save_result("wf_123", "task_1", "generalPurpose", "do something", {"cached": True})

    mock_manager = AsyncMock(spec=SubagentManager)

    tool = SpawnSubagentTool(
        manager=mock_manager,
        tool_registry_getter=lambda: [],
        workflow_id="wf_123",
        store=temp_store,
    )

    result = await tool._arun("task_1", "generalPurpose", "do something")

    assert result == {"cached": True}
    mock_manager.spawn_child.assert_not_called()

@pytest.mark.asyncio
async def test_spawn_tool_cache_miss(temp_store):
    mock_manager = AsyncMock(spec=SubagentManager)

    # Mock the return value of spawn_child
    class MockResult:
        success = True
        task_id = "task_1"
        agent_type = "generalPurpose"
        result = "done"
        error = None

    mock_manager.spawn_child.return_value = MockResult()

    tool = SpawnSubagentTool(
        manager=mock_manager,
        tool_registry_getter=lambda: [],
        workflow_id="wf_123",
        store=temp_store,
    )

    result = await tool._arun("task_1", "generalPurpose", "do something")

    assert result["success"] is True
    assert result["result"] == "done"

    mock_manager.spawn_child.assert_called_once()

    # Verify it was saved
    cached = temp_store.get_cached_result("wf_123", "task_1")
    assert cached is not None
    assert cached["result"] == "done"


@pytest.mark.asyncio
async def test_spawn_tool_dict_result():
    """spawn_child may return a dict directly — must pass through unchanged."""
    mock_manager = AsyncMock(spec=SubagentManager)
    mock_manager.spawn_child.return_value = {"success": True, "result": "dict-path"}

    tool = SpawnSubagentTool(
        manager=mock_manager,
        tool_registry_getter=lambda: [],
        workflow_id="wf_dict",
        store=None,
    )

    result = await tool._arun("task_x", "generalPurpose", "do something")
    assert result == {"success": True, "result": "dict-path"}


def test_spawn_tool_sync_raises():
    """Sync _run must raise — tool is async-only."""
    mock_manager = MagicMock(spec=SubagentManager)
    tool = SpawnSubagentTool(
        manager=mock_manager,
        tool_registry_getter=lambda: [],
        workflow_id="wf_sync",
        store=None,
    )
    with pytest.raises(NotImplementedError):
        tool._run("t1", "generalPurpose", "desc")
