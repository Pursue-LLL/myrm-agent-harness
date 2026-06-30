"""LangChain adapters for user interaction primitives.

[INPUT]
- ask_question::AskQuestionInput (POS: structured clarification form schema)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: client action transport)

[OUTPUT]
- AskQuestionTool: LangChain tool for structured user clarification.
- write_to_clipboard: LangChain tool for host clipboard via client action.
- create_ask_question_tool: Factory binding a runtime callback to AskQuestionTool.
- create_clipboard_tools: Factory returning clipboard LangChain tools.

[POS]
Optional LangChain adapter layer per toolkits/_ARCH.md. Schemas remain in ask_question.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, PrivateAttr

from myrm_agent_harness.toolkits.interaction.ask_question import AskQuestionInput
from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink


class AskQuestionTool(BaseTool):
    """Tool for asking the user structured questions."""

    name: str = "ask_question_tool"
    tags: list[str] = ["interactive"]
    description: str = (
        "Ask the user one or more clarifying questions. Use this when the request is ambiguous, "
        "or when you need to confirm intent, choose between options, or gather missing details "
        "before proceeding. You can provide predefined options with descriptions, or leave options "
        "empty for open-ended questions.\n"
        "CRITICAL: You can only call this tool ONCE per turn. If you have multiple questions, "
        "put ALL of them in the `questions` list of a SINGLE tool call. Do NOT call this tool "
        "multiple times in parallel."
    )
    args_schema: type[BaseModel] = AskQuestionInput

    _callback: Callable[[AskQuestionInput], Awaitable[str]] = PrivateAttr()

    def __init__(self, callback: Callable[[AskQuestionInput], Awaitable[str]]) -> None:
        super().__init__()
        self._callback = callback

    async def _arun(self, **kwargs: object) -> str:
        input_data = AskQuestionInput.model_validate(kwargs)
        return await self._callback(input_data)

    def _run(self, **kwargs: object) -> str:
        raise NotImplementedError("AskQuestionTool only supports async execution.")


def create_ask_question_tool(callback: Callable[[AskQuestionInput], Awaitable[str]]) -> AskQuestionTool:
    """Create an ask_question LangChain tool bound to a runtime HITL callback."""
    return AskQuestionTool(callback=callback)


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
        await sink.emit({"type": "client_action", "data": {"action": "write_clipboard", "payload": {"text": text}}})
        await asyncio.sleep(0.5)
        return "Successfully requested the client to copy the text to the clipboard."
    return "Error: Client connection not available to perform clipboard write."


def create_clipboard_tools() -> list[BaseTool]:
    """Return LangChain clipboard tools for agent registration."""
    return [write_to_clipboard]
