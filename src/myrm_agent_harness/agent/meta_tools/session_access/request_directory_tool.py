"""LangChain adapter for request_directory HITL session access grants."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, PrivateAttr

from myrm_agent_harness.agent.meta_tools.session_access.request_directory import (
    RequestDirectoryInput,
)


def _format_directory_interrupt_response(response: object) -> str:
    if not response:
        return json.dumps({"granted": False, "error": "User declined or timed out"})
    if isinstance(response, dict):
        return json.dumps(response, ensure_ascii=False)
    return json.dumps({"granted": False, "error": "Invalid directory grant response"})


def _interrupt_directory_request(form: RequestDirectoryInput) -> str:
    from langgraph.types import interrupt

    payload = {"type": "directory_request", "request": form.model_dump()}
    return _format_directory_interrupt_response(interrupt(payload))


class RequestDirectoryTool(BaseTool):
    name: str = "request_directory_tool"
    tags: list[str] = ["interactive"]
    description: str = (
        "Ask the user to grant access to a directory outside the current workspace roots. "
        "Use when the task requires reading or writing files in a folder you cannot reach yet. "
        "Provide a clear reason and optional suggested path. Set writable=true only when writes "
        "are required. Do not use to bypass sandbox security."
    )
    args_schema: type[BaseModel] = RequestDirectoryInput

    _callback: Callable[[RequestDirectoryInput], Awaitable[str]] = PrivateAttr()

    def __init__(self, callback: Callable[[RequestDirectoryInput], Awaitable[str]]) -> None:
        super().__init__()
        self._callback = callback

    async def _arun(self, **kwargs: object) -> str:
        input_data = RequestDirectoryInput.model_validate(kwargs)
        return await self._callback(input_data)

    def _run(self, **kwargs: object) -> str:
        input_data = RequestDirectoryInput.model_validate(kwargs)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._arun(**kwargs))
        return _interrupt_directory_request(input_data)


def create_request_directory_tool(
    callback: Callable[[RequestDirectoryInput], Awaitable[str]],
) -> BaseTool:
    return RequestDirectoryTool(callback)
