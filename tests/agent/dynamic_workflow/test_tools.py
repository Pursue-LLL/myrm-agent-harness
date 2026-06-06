"""Unit tests for SpawnSubagentTool."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.tools import SpawnSubagentTool


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        store = WorkflowEventStore(db_path)
        yield store


@pytest.fixture
def mock_parent_agent():
    agent = MagicMock()
    agent._cached_tools = []
    agent.user_tools = []
    agent._spawn_child = AsyncMock()
    return agent


@pytest.mark.asyncio
async def test_spawn_tool_cache_hit(temp_store, mock_parent_agent):
    temp_store.save_result("wf_123", "task_1", "generalPurpose", "do something", {"cached": True})

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_123",
        store=temp_store,
    )

    result = await tool._arun("task_1", "generalPurpose", "do something")

    assert result == {"cached": True}
    mock_parent_agent._spawn_child.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_cache_miss(temp_store, mock_parent_agent):
    class MockResult:
        success = True
        task_id = "task_1"
        agent_type = "generalPurpose"
        result = "done"
        error = None

    mock_parent_agent._spawn_child.return_value = MockResult()

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_123",
        store=temp_store,
    )

    result = await tool._arun("task_1", "generalPurpose", "do something")

    assert result["success"] is True
    assert result["result"] == "done"

    mock_parent_agent._spawn_child.assert_called_once()

    cached = temp_store.get_cached_result("wf_123", "task_1")
    assert cached is not None
    assert cached["result"] == "done"


@pytest.mark.asyncio
async def test_spawn_tool_dict_result(mock_parent_agent):
    """spawn_child may return a dict directly — must pass through unchanged."""
    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "dict-path"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_dict",
        store=None,
    )

    result = await tool._arun("task_x", "generalPurpose", "do something")
    assert result == {"success": True, "result": "dict-path"}


def test_spawn_tool_sync_raises(mock_parent_agent):
    """Sync _run must raise — tool is async-only."""
    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_sync",
        store=None,
    )
    with pytest.raises(NotImplementedError):
        tool._run("t1", "generalPurpose", "desc")


@pytest.mark.asyncio
async def test_spawn_tool_cancel_token_respected(mock_parent_agent):
    """Cancelled token prevents spawning."""
    cancel_token = MagicMock()
    cancel_token.is_cancelled = True

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_cancel",
        store=None,
        cancel_token=cancel_token,
    )

    result = await tool._arun("task_1", "generalPurpose", "do something")

    assert result["success"] is False
    assert "cancelled" in result["error"].lower()
    mock_parent_agent._spawn_child.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_catalog_resolve(mock_parent_agent):
    """Catalog is used to resolve SubagentConfig when available."""
    from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

    custom_config = SubagentConfig(
        system_prompt="Custom prompt",
        max_spawn_depth=1,
        concurrency_limit=5,
        max_cost_usd=3.0,
        budget_tokens=300_000,
    )

    mock_catalog = AsyncMock()
    mock_catalog.resolve.return_value = custom_config

    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "catalog-used"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_catalog",
        catalog=mock_catalog,
        store=None,
    )

    result = await tool._arun("task_1", "coder", "write code")

    mock_catalog.resolve.assert_called_once_with("coder")
    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    assert call_kwargs["config"] is custom_config
    assert result["success"] is True


@pytest.mark.asyncio
async def test_spawn_tool_catalog_fallback(mock_parent_agent):
    """Falls back to default config when catalog returns None."""
    mock_catalog = AsyncMock()
    mock_catalog.resolve.return_value = None

    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "fallback"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_fallback",
        catalog=mock_catalog,
        store=None,
    )

    result = await tool._arun("task_1", "unknown_type", "task desc")

    mock_catalog.resolve.assert_called_once_with("unknown_type")
    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    assert call_kwargs["config"].max_cost_usd == 2.0
    assert result["success"] is True


@pytest.mark.asyncio
async def test_spawn_tool_exception_handling(mock_parent_agent):
    """Exceptions from _spawn_child are caught and returned as error dict."""
    mock_parent_agent._spawn_child.side_effect = RuntimeError("connection lost")

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_error",
        store=None,
    )

    result = await tool._arun("task_1", "generalPurpose", "do something")

    assert result["success"] is False
    assert "RuntimeError" in result["error"]
    assert "connection lost" in result["error"]
