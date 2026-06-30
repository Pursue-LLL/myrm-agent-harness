"""LangChain adapters for user interaction primitives.

[INPUT]
- ask_question::AskQuestionInput (POS: structured clarification form schema)

[OUTPUT]
- AskQuestionTool: LangChain tool for structured user clarification.
- create_ask_question_tool: Factory binding a runtime callback to AskQuestionTool.

[POS]
Optional LangChain adapter layer per toolkits/_ARCH.md. Schemas remain in ask_question.py.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, PrivateAttr

from myrm_agent_harness.toolkits.interaction.ask_question import AskQuestionInput


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
