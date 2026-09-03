"""LangChain adapter for ask_question HITL clarification.

[INPUT]
- clarification.ask_question::AskQuestionInput (POS: structured clarification form schema)
- clarification._ask_question_descriptions::resolve_ask_question_tool_description (POS: localized prompt SSOT)

[OUTPUT]
- AskQuestionTool: LangChain tool for structured user clarification.
- create_ask_question_tool: Factory binding a runtime HITL callback and optional locale to AskQuestionTool.

[POS]
Agent meta-tool adapter for clarification forms. Runtime interrupt binding is injected by server.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from myrm_agent_harness.agent.meta_tools.clarification._ask_question_descriptions import (
    ASK_QUESTION_TOOL_DESCRIPTION,
    resolve_ask_question_tool_description,
)
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
    tags: list[str] = Field(default_factory=lambda: ["interactive"])
    description: str = ASK_QUESTION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = AskQuestionInput

    _callback: Callable[[AskQuestionInput], Awaitable[str]] = PrivateAttr()

    def __init__(
        self,
        callback: Callable[[AskQuestionInput], Awaitable[str]],
        locale: str | None = None,
    ) -> None:
        super().__init__()
        self._callback = callback
        if locale:
            self.description = resolve_ask_question_tool_description(locale)

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
    locale: str | None = None,
) -> AskQuestionTool:
    """Create an ask_question LangChain tool bound to a runtime HITL callback."""
    return AskQuestionTool(callback=callback, locale=locale)
