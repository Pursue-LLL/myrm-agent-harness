from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult


@pytest.fixture
def mock_agent():
    """Create a minimal mock BaseAgent for testing."""
    agent = BaseAgent(
        llm=MagicMock(),
        tools=[],
        system_prompt="You are a test agent."
    )
    # Mock the context to provide a session_id and agent_id
    agent._last_context = {
        "session_id": "test-session-123",
        "agent_id": "test-parent-agent"
    }
    return agent


@pytest.mark.asyncio
@patch("myrm_agent_harness.utils.runtime.wakeup_registry.get_global_wakeup_handler")
@patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink")
async def test_trigger_async_wakeup_with_handler_and_sink(
    mock_get_sink, mock_get_handler, mock_agent
):
    """Test that trigger_async_wakeup calls both the global handler and the progress sink."""
    # Setup mocks
    mock_handler = AsyncMock()
    mock_get_handler.return_value = mock_handler

    mock_sink = AsyncMock()
    mock_get_sink.return_value = mock_sink

    # Create a dummy result
    result = SubAgentResult(
        task_id="task-001",
        agent_type="test_subagent",
        success=True,
    )

    # Call the method
    await mock_agent.trigger_async_wakeup(result)

    # Verify global handler was called
    mock_handler.on_async_wakeup.assert_awaited_once_with(
        result, "test-parent-agent", "test-session-123"
    )

    # Verify progress sink was called
    mock_sink.emit.assert_awaited_once_with({
        "type": AgentEventType.ASYNC_WAKEUP.value,
        "data": {
            "task_id": "task-001",
            "agent_type": "test_subagent",
            "success": True,
            "agent_id": "test-parent-agent",
            "session_id": "test-session-123",
        }
    })


@pytest.mark.asyncio
@patch("myrm_agent_harness.utils.runtime.wakeup_registry.get_global_wakeup_handler")
@patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink")
async def test_trigger_async_wakeup_no_handler_no_sink(
    mock_get_sink, mock_get_handler, mock_agent
):
    """Test that trigger_async_wakeup handles None returned by getters gracefully."""
    # Setup mocks to return None
    mock_get_handler.return_value = None
    mock_get_sink.return_value = None

    # Create a dummy result
    result = SubAgentResult(
        task_id="task-002",
        agent_type="test_subagent",
        success=False,
    )

    # Call the method - should not raise any exceptions
    await mock_agent.trigger_async_wakeup(result)


@pytest.mark.asyncio
@patch("myrm_agent_harness.utils.runtime.wakeup_registry.get_global_wakeup_handler")
@patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink")
async def test_trigger_async_wakeup_exception_handling(
    mock_get_sink, mock_get_handler, mock_agent
):
    """Test that trigger_async_wakeup catches exceptions from handler/sink and continues."""
    # Setup mocks to raise exceptions
    mock_handler = AsyncMock()
    mock_handler.on_async_wakeup.side_effect = Exception("Handler failed")
    mock_get_handler.return_value = mock_handler

    mock_sink = AsyncMock()
    mock_sink.emit.side_effect = Exception("Sink failed")
    mock_get_sink.return_value = mock_sink

    # Create a dummy result
    result = SubAgentResult(
        task_id="task-003",
        agent_type="test_subagent",
        success=True,
    )

    # Call the method - should catch exceptions and not raise them
    await mock_agent.trigger_async_wakeup(result)

    # Verify both were still called despite the first one failing
    mock_handler.on_async_wakeup.assert_awaited_once()
    mock_sink.emit.assert_awaited_once()
