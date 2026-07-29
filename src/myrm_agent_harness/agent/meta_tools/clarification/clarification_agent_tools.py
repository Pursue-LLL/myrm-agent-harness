"""LangChain adapter for ask_question HITL clarification.

[INPUT]
- clarification.ask_question::AskQuestionInput (POS: structured clarification form schema)

[OUTPUT]
- AskQuestionTool: LangChain tool for structured user clarification.
- create_ask_question_tool: Factory binding a runtime HITL callback to AskQuestionTool.

[POS]
Agent meta-tool adapter for clarification forms. Runtime interrupt binding is injected by server.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, PrivateAttr

from myrm_agent_harness.agent.meta_tools.clarification.ask_question import (
    AskQuestionInput,
)


def _format_ask_question_interrupt_response(response: object) -> str:
    if not response:
        return (
            "User did not answer the clarification (skipped or timed out). "
            "Proceed with your best judgment; do not wait for further input."
        )
    return json.dumps(response, ensure_ascii=False)


def _interrupt_ask_question_form(form: AskQuestionInput) -> str:
    from langgraph.types import interrupt

    payload = {"type": "ask_question", "form": form.model_dump()}
    return _format_ask_question_interrupt_response(interrupt(payload))


class AskQuestionTool(BaseTool):
    """Tool for asking the user structured questions."""

    name: str = "ask_question_tool"
    tags: list[str] = ["interactive"]
    description: str = (
        "Ask the user one or more clarifying questions. Use this when the request is ambiguous, "
        "or when you need to confirm intent, choose between options, or gather missing details "
        "before proceeding. Set requires_confirmation=true before destructive or irreversible work. "
        "You can provide predefined options with descriptions, or leave options "
        "empty for open-ended questions.\n"
        "CRITICAL: You can only call this tool ONCE per turn. If you have multiple questions, "
        "put ALL of them in the `questions` list of a SINGLE tool call. Do NOT call this tool "
        "multiple times in parallel or alongside other tools in the same turn."
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
        input_data = AskQuestionInput.model_validate(kwargs)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._arun(**kwargs))

        # Sync ToolNode while agent astream holds the loop: interrupt must run on this
        # thread. Thread-pool asyncio.run() breaks GraphInterrupt propagation (R142 warm).
        return _interrupt_ask_question_form(input_data)


def create_ask_question_tool(
    callback: Callable[[AskQuestionInput], Awaitable[str]],
) -> AskQuestionTool:
    """Create an ask_question LangChain tool bound to a runtime HITL callback."""
    return AskQuestionTool(callback=callback)
