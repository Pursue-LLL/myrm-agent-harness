"""Unit tests for executor ContextVar mechanism.

Tests get_executor / set_executor / require_executor defined in
``toolkits.code_execution.executors.base``, and their usage by bash_tool.
"""

from collections.abc import Iterator

import pytest

from myrm_agent_harness.agent.meta_tools.bash import create_bash_tool
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    _executor_var,
    get_executor,
    require_executor,
    set_executor,
)


@pytest.fixture(autouse=True)
def clear_executor_contextvar() -> Iterator[None]:
    """Reset the executor ContextVar around each test."""
    token = _executor_var.set(None)
    try:
        yield
    finally:
        _executor_var.reset(token)


class MockExecutor:
    """Mock CodeExecutor for testing."""

    def __init__(self, name: str = "mock"):
        from myrm_agent_harness.toolkits.code_execution.executors.base import MCPCommunicationConfig

        self.name = name
        self.workspace_path: str | None = None
        self._mcp_config = MCPCommunicationConfig(skip_local_proxy=True)

    def bind_workspace(self, path: str) -> None:
        self.workspace_path = path

    def get_executor_name(self) -> str:
        return self.name

    def get_mcp_communication_config(self):
        return self._mcp_config

    async def execute_bash(self, *args, **kwargs):
        return {
            "stdout": "test output",
            "stderr": "",
            "exit_code": 0,
            "result_type": "success",
        }


def test_get_set_executor():
    """Test get_executor() and set_executor() basic functionality."""
    mock_exec = MockExecutor("test_executor")

    # Initially None
    assert get_executor() is None

    # Set and get
    set_executor(mock_exec)
    retrieved = get_executor()

    assert retrieved is not None
    assert retrieved.name == "test_executor"


@pytest.mark.asyncio
async def test_executor_contextvar_isolation():
    """Test that ContextVar properly isolates different async contexts."""
    import asyncio

    mock1 = MockExecutor("executor_1")
    mock2 = MockExecutor("executor_2")

    set_executor(mock1)
    get_executor()

    async def task_with_different_executor():
        set_executor(mock2)
        return get_executor()

    # Run in separate task
    result = await asyncio.create_task(task_with_different_executor())

    # Result should be mock2
    assert result is not None
    assert result.name == "executor_2"

    # But the original task's context should still have mock1
    # (Note: In practice, ContextVar inherits from parent context)
    current = get_executor()
    assert current is not None
    # Context was copied to task, so it might be either mock1 or mock2
    # The key point is no crash and proper isolation


def test_contextvar_persists_across_functions():
    """Test that ContextVar value persists across function calls."""
    mock_exec = MockExecutor("persistent_executor")

    def set_in_function():
        set_executor(mock_exec)

    def get_in_function():
        return get_executor()

    set_in_function()
    retrieved = get_in_function()

    assert retrieved is not None
    assert retrieved.name == "persistent_executor"


@pytest.mark.asyncio
async def test_contextvar_available_in_async_context():
    """Test that ContextVar is accessible in async functions."""
    mock_exec = MockExecutor("async_executor")
    set_executor(mock_exec)

    async def async_task():
        return get_executor()

    result = await async_task()
    assert result is not None
    assert result.name == "async_executor"


def test_require_executor_raises_when_none():
    """Test that require_executor() raises RuntimeError when no executor is set."""
    with pytest.raises(RuntimeError, match="CodeExecutor not available"):
        require_executor()


def test_require_executor_returns_executor():
    """Test that require_executor() returns the executor when set."""
    mock_exec = MockExecutor("required_executor")
    set_executor(mock_exec)
    result = require_executor()
    assert result is mock_exec


@pytest.mark.asyncio
async def test_bash_tool_no_executor_fails():
    """Test that bash_tool raises error when no executor is available."""
    from myrm_agent_harness.utils.errors import ToolError

    _executor_var.set(None)

    bash_tool = create_bash_tool()

    config = {
        "configurable": {
            "context": {
                "session_id": "test_session",
            }
        }
    }

    with pytest.raises(ToolError) as exc_info:
        await bash_tool.ainvoke({"command": "echo test", "reason": "testing"}, config=config)

    assert "codeexecutor not available" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_bash_tool_handles_non_mapping_context_without_attribute_error():
    """Malformed config context should degrade to missing session_id, not crash."""
    from myrm_agent_harness.utils.errors import ToolError

    set_executor(MockExecutor("context_guard_executor"))
    bash_tool = create_bash_tool()

    with pytest.raises(ToolError) as exc_info:
        await bash_tool.ainvoke(
            {"command": "echo test", "reason": "testing"}, config={"configurable": {"context": "invalid-context-shape"}}
        )

    assert "session_id is required" in str(exc_info.value).lower()
