import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
    emit_tool_heartbeat as _emit_tool_heartbeat,
)
from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
    _tool_interceptor_middleware_inner,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType


@pytest.mark.asyncio
async def test_emit_tool_heartbeat():
    """Test that _emit_tool_heartbeat emits events correctly."""
    tool_name = "test_tool"
    tool_call_id = "call_123"
    start_time = time.time()

    mock_sink = AsyncMock()
    mock_sink.emit = AsyncMock()

    with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=mock_sink):
        # We don't want to wait 3 seconds in a unit test, so we patch asyncio.sleep
        # but we need to let the event loop run
        sleep_calls = 0
        async def fake_sleep(delay):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls > 1:
                raise asyncio.CancelledError()
            return

        with patch("asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await _emit_tool_heartbeat(tool_name, tool_call_id, start_time)

            assert mock_sink.emit.call_count >= 1
            call_args = mock_sink.emit.call_args[0][0]
            assert call_args["type"] == AgentEventType.TOOL_HEARTBEAT.value
            assert call_args["tool_name"] == tool_name
            assert call_args["tool_call_id"] == tool_call_id
            assert "elapsed_ms" in call_args


@pytest.mark.asyncio
async def test_tool_interceptor_starts_and_cancels_heartbeat():
    """Test that _tool_interceptor_middleware_inner starts and cancels the heartbeat task."""
    request = ToolCallRequest(
        tool_call={"name": "test_tool", "id": "call_123", "args": {}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock()
    )

    async def dummy_handler(req):
        return ToolMessage(content="success", name="test_tool", tool_call_id="call_123")

    with patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.run_pre_call_guards", return_value=MagicMock()), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.execute_with_retry", return_value=ToolMessage(content="success", name="test_tool", tool_call_id="call_123")), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.run_post_call_guards", return_value=ToolMessage(content="success", name="test_tool", tool_call_id="call_123")), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.emit_tool_heartbeat") as mock_emit, \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.push_tool_context"), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.pop_tool_context"), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_token_tracker", return_value=None):

        # Make _emit_tool_heartbeat an async function that just sleeps forever
        # so it can be cancelled
        async def fake_heartbeat(*args, **kwargs):
            await asyncio.sleep(100)

        mock_emit.side_effect = fake_heartbeat

        await _tool_interceptor_middleware_inner(request, dummy_handler)

        # Verify heartbeat task was created and called
        assert mock_emit.call_count == 1
        assert mock_emit.call_args[0][0] == "test_tool"
        assert mock_emit.call_args[0][1] == "call_123"
