from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.interaction.clipboard_tools import write_to_clipboard


@pytest.mark.asyncio
async def test_write_to_clipboard_with_sink():
    """Test that write_to_clipboard emits the correct event when sink is available."""
    mock_sink = AsyncMock()

    with patch("myrm_agent_harness.toolkits.interaction.clipboard_tools.get_tool_progress_sink", return_value=mock_sink):
        result = await write_to_clipboard.ainvoke({"text": "hello world"})

        assert "Successfully requested" in result
        mock_sink.emit.assert_called_once()
        emitted_event = mock_sink.emit.call_args[0][0]
        assert emitted_event["type"] == "client_action"
        assert emitted_event["data"]["action"] == "write_clipboard"
        assert emitted_event["data"]["payload"]["text"] == "hello world"

@pytest.mark.asyncio
async def test_write_to_clipboard_without_sink():
    """Test that write_to_clipboard returns an error when sink is not available."""
    with patch("myrm_agent_harness.toolkits.interaction.clipboard_tools.get_tool_progress_sink", return_value=None):
        result = await write_to_clipboard.ainvoke({"text": "hello world"})

        assert "Error: Client connection not available" in result
