"""Unit tests for SpawnSubagentTool and NotifyProgressTool."""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.tools import (
    NotifyProgressTool,
    SpawnSubagentTool,
)


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


@pytest.mark.asyncio
async def test_spawn_tool_readonly_enforces_sandbox_policy(mock_parent_agent):
    """readonly=True sets workspace_policy=READ_ONLY_SANDBOX on the config."""
    from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy

    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "read-only"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly",
        store=None,
    )

    await tool._arun("task_1", "generalPurpose", "scan for vulnerabilities", readonly=True)

    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    config = call_kwargs["config"]
    assert config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX


@pytest.mark.asyncio
async def test_spawn_tool_readonly_blocks_write_tools(mock_parent_agent):
    """readonly=True adds write tools to disallowed_tools."""
    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "ok"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_tools",
        store=None,
    )

    await tool._arun("task_1", "generalPurpose", "audit code quality", readonly=True)

    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    config = call_kwargs["config"]
    assert "write_file" in config.disallowed_tools
    assert "execute_terminal_command" in config.disallowed_tools
    assert "bash_run_command" in config.disallowed_tools
    assert "git_commit" in config.disallowed_tools


@pytest.mark.asyncio
async def test_spawn_tool_readonly_appends_prompt_hint(mock_parent_agent):
    """readonly=True appends [READONLY MODE] hint to system_prompt."""
    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "ok"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_hint",
        store=None,
    )

    await tool._arun("task_1", "generalPurpose", "review security", readonly=True)

    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    config = call_kwargs["config"]
    assert "[READONLY MODE]" in config.system_prompt


@pytest.mark.asyncio
async def test_spawn_tool_readonly_false_no_enforcement(mock_parent_agent):
    """readonly=False (default) does not modify config."""
    from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy

    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "ok"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_no_readonly",
        store=None,
    )

    await tool._arun("task_1", "generalPurpose", "write some code", readonly=False)

    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    config = call_kwargs["config"]
    assert config.workspace_policy == WorkspacePolicy.INHERIT
    assert "write_file" not in config.disallowed_tools
    assert "[READONLY MODE]" not in config.system_prompt


@pytest.mark.asyncio
async def test_spawn_tool_readonly_with_catalog_config(mock_parent_agent):
    """readonly=True works correctly with catalog-resolved config."""
    from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy

    custom_config = SubagentConfig(
        system_prompt="I am a security scanner.",
        max_spawn_depth=0,
        disallowed_tools=frozenset({"existing_blocked"}),
    )

    mock_catalog = AsyncMock()
    mock_catalog.resolve.return_value = custom_config
    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "scanned"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_catalog",
        catalog=mock_catalog,
        store=None,
    )

    await tool._arun("task_1", "scanner", "scan codebase", readonly=True)

    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    config = call_kwargs["config"]
    assert config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX
    assert "existing_blocked" in config.disallowed_tools
    assert "write_file" in config.disallowed_tools
    assert "[READONLY MODE]" in config.system_prompt
    assert "I am a security scanner." in config.system_prompt


@pytest.mark.asyncio
async def test_spawn_tool_readonly_cancel_takes_priority(mock_parent_agent):
    """Cancel token fires before readonly enforcement — no spawn happens."""
    cancel_token = MagicMock()
    cancel_token.is_cancelled = True

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_cancel",
        store=None,
        cancel_token=cancel_token,
    )

    result = await tool._arun("task_1", "generalPurpose", "audit code", readonly=True)

    assert result["success"] is False
    assert "cancelled" in result["error"].lower()
    mock_parent_agent._spawn_child.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_readonly_cache_takes_priority(temp_store, mock_parent_agent):
    """Cache hit returns before readonly enforcement — no spawn happens."""
    temp_store.save_result("wf_rc", "task_1", "generalPurpose", "scan", {"cached": True, "result": "old"})

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_rc",
        store=temp_store,
    )

    result = await tool._arun("task_1", "generalPurpose", "scan", readonly=True)

    assert result == {"cached": True, "result": "old"}
    mock_parent_agent._spawn_child.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_tool_readonly_exception_still_caught(mock_parent_agent):
    """readonly=True + _spawn_child raises → error dict returned, not crash."""
    mock_parent_agent._spawn_child.side_effect = PermissionError("fs locked")

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_err",
        store=None,
    )

    result = await tool._arun("task_1", "generalPurpose", "audit", readonly=True)

    assert result["success"] is False
    assert "PermissionError" in result["error"]
    assert "fs locked" in result["error"]


@pytest.mark.asyncio
async def test_spawn_tool_readonly_with_object_result(mock_parent_agent):
    """readonly=True with non-dict result object — status extraction works."""
    from enum import Enum

    class Status(Enum):
        COMPLETED = "completed"

    class MockResult:
        success = True
        task_id = "task_1"
        agent_type = "generalPurpose"
        result = "analysis done"
        error = None
        status = Status.COMPLETED

    mock_parent_agent._spawn_child.return_value = MockResult()

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_obj",
        store=None,
    )

    result = await tool._arun("task_1", "generalPurpose", "analyze", readonly=True)

    assert result["success"] is True
    assert result["result"] == "analysis done"
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_spawn_tool_readonly_preserves_model_resolver(mock_parent_agent):
    """readonly=True on default config preserves parent's model_resolver."""
    mock_resolver = MagicMock()
    mock_parent_agent.model_resolver = mock_resolver
    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "ok"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_resolver",
        store=None,
    )

    await tool._arun("task_1", "generalPurpose", "scan", readonly=True)

    call_kwargs = mock_parent_agent._spawn_child.call_args[1]
    config = call_kwargs["config"]
    assert config.model_resolver is mock_resolver


@pytest.mark.asyncio
async def test_spawn_tool_readonly_store_saves_result(temp_store, mock_parent_agent):
    """readonly=True result is still persisted to store."""
    mock_parent_agent._spawn_child.return_value = {"success": True, "result": "scanned"}

    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_readonly_store",
        store=temp_store,
    )

    result = await tool._arun("task_1", "generalPurpose", "scan", readonly=True)

    assert result["success"] is True
    cached = temp_store.get_cached_result("wf_readonly_store", "task_1")
    assert cached is not None
    assert cached["result"] == "scanned"


@pytest.mark.asyncio
async def test_spawn_tool_sync_run_readonly_raises(mock_parent_agent):
    """Sync _run with readonly=True still raises NotImplementedError."""
    tool = SpawnSubagentTool(
        parent_agent=mock_parent_agent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_sync_ro",
        store=None,
    )
    with pytest.raises(NotImplementedError):
        tool._run("t1", "generalPurpose", "desc", readonly=True)


# ---------------------------------------------------------------------------
# NotifyProgressTool tests
# ---------------------------------------------------------------------------

@pytest.fixture
def notify_queue():
    return asyncio.Queue()


@pytest.fixture
def notify_tool(notify_queue):
    return NotifyProgressTool(event_queue=notify_queue, message_id="msg_test_123")


@pytest.mark.asyncio
async def test_notify_basic(notify_tool, notify_queue):
    """Basic notify emits correct event structure."""
    result = await notify_tool._arun(message="Phase 1: Collecting data")
    assert result["success"] is True
    assert notify_queue.qsize() == 1

    event = notify_queue.get_nowait()
    assert event["type"] == "status"
    assert event["step_key"] == "workflow_stage"
    assert event["messageId"] == "msg_test_123"
    assert event["status"] == "in_progress"
    assert event["data"]["message"] == "Phase 1: Collecting data"


@pytest.mark.asyncio
async def test_notify_with_progress(notify_tool, notify_queue):
    """Notify with progress fields populates data correctly."""
    result = await notify_tool._arun(
        message="Analyzing files",
        progress=42,
        step_index=2,
        total_steps=5,
        category="analysis",
        level="info",
    )
    assert result["success"] is True
    event = notify_queue.get_nowait()
    data = event["data"]
    assert data["notify_progress"] == 42
    assert data["notify_step_index"] == 2
    assert data["notify_total_steps"] == 5
    assert data["notify_category"] == "analysis"
    assert data["notify_level"] == "info"


@pytest.mark.asyncio
async def test_notify_progress_clamped(notify_tool, notify_queue):
    """Progress is clamped to [-1, 100]."""
    await notify_tool._arun(message="overflow", progress=200)
    event = notify_queue.get_nowait()
    assert event["data"]["notify_progress"] == 100

    await notify_tool._arun(message="underflow", progress=-50)
    event = notify_queue.get_nowait()
    assert event["data"]["notify_progress"] == -1


@pytest.mark.asyncio
async def test_notify_message_truncated(notify_tool, notify_queue):
    """Long messages are truncated to 500 chars."""
    long_msg = "x" * 1000
    result = await notify_tool._arun(message=long_msg)
    assert len(result["message"]) == 500
    event = notify_queue.get_nowait()
    assert len(event["data"]["message"]) == 500


@pytest.mark.asyncio
async def test_notify_invalid_level_defaults_to_info(notify_tool, notify_queue):
    """Invalid level falls back to 'info'."""
    await notify_tool._arun(message="test", level="critical")
    event = notify_queue.get_nowait()
    assert event["data"]["notify_level"] == "info"


@pytest.mark.asyncio
async def test_notify_valid_levels(notify_tool, notify_queue):
    """All valid levels are accepted."""
    for level in ("info", "warn", "alert"):
        await notify_tool._arun(message=f"test {level}", level=level)
        event = notify_queue.get_nowait()
        assert event["data"]["notify_level"] == level


@pytest.mark.asyncio
async def test_notify_category_truncated(notify_tool, notify_queue):
    """Long category is truncated to 100 chars."""
    long_cat = "c" * 200
    await notify_tool._arun(message="test", category=long_cat)
    event = notify_queue.get_nowait()
    assert len(event["data"]["notify_category"]) == 100


@pytest.mark.asyncio
async def test_notify_sync_run_raises(notify_queue):
    """Sync _run raises NotImplementedError."""
    tool = NotifyProgressTool(event_queue=notify_queue, message_id="msg")
    with pytest.raises(NotImplementedError):
        tool._run("test message")


@pytest.mark.asyncio
async def test_notify_multiple_events(notify_tool, notify_queue):
    """Multiple notify calls queue events in order."""
    await notify_tool._arun(message="Phase 1", step_index=1, total_steps=3)
    await notify_tool._arun(message="Phase 2", step_index=2, total_steps=3)
    await notify_tool._arun(message="Phase 3", step_index=3, total_steps=3)

    assert notify_queue.qsize() == 3
    events = [notify_queue.get_nowait() for _ in range(3)]
    assert [e["data"]["message"] for e in events] == ["Phase 1", "Phase 2", "Phase 3"]
    assert [e["data"]["notify_step_index"] for e in events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_notify_negative_step_index_clamped(notify_tool, notify_queue):
    """Negative step_index and total_steps are clamped to 0."""
    await notify_tool._arun(message="test", step_index=-5, total_steps=-3)
    event = notify_queue.get_nowait()
    assert event["data"]["notify_step_index"] == 0
    assert event["data"]["notify_total_steps"] == 0


@pytest.mark.asyncio
async def test_notify_indeterminate_progress(notify_tool, notify_queue):
    """Default progress=-1 represents indeterminate state."""
    await notify_tool._arun(message="Working...")
    event = notify_queue.get_nowait()
    assert event["data"]["notify_progress"] == -1
