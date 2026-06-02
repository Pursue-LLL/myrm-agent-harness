"""Clipboard interaction tools.

[INPUT]
- agent.streaming.types::AgentEventType (POS: Agent stream event types)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: Sink for emitting real-time tool progress)

[OUTPUT]
- write_to_clipboard: Tool to write text to the user's clipboard via client action.

[POS]
Provides tools for the agent to interact with the user's OS clipboard via the client frontend.
"""

import asyncio

from langchain_core.tools import tool

from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink


@tool("write_to_clipboard_tool")
async def write_to_clipboard(text: str) -> str:
    """Write text to the user's OS clipboard.

    This tool sends a request to the user's client (Desktop/Web) to copy the text to their clipboard.
    Use this when the user asks you to generate a command, code snippet, or text and you want to save them the trouble of manually copying it.

    IMPORTANT: ALWAYS use this tool to write to the clipboard. DO NOT use bash, python3, pbcopy, xclip, or clip to write to the clipboard, as those commands run in an isolated sandbox and will not affect the user's actual host clipboard.
    CRITICAL: DO NOT output XML tags like `<tool_call>`. You MUST use the native tool calling API (function calling) to invoke this tool.

    Args:
        text: The exact text to be copied to the clipboard.
    """
    sink = get_tool_progress_sink()
    if sink:
        # Emit a special event for the client to execute the clipboard write
        await sink.emit({
            "type": "client_action",
            "data": {
                "action": "write_clipboard",
                "payload": {"text": text}
            }
        })
        # Wait a moment to ensure the event is sent
        await asyncio.sleep(0.5)
        return "Successfully requested the client to copy the text to the clipboard."
    else:
        return "Error: Client connection not available to perform clipboard write."
