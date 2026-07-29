"""Sync hook parity for LangGraph sync tool/model paths (R142 signoff clarify).

LangChain AgentMiddleware defaults raise NotImplementedError on sync
``wrap_tool_call`` / ``wrap_model_call`` when only async hooks are defined.
Signoff clarify pool warm executes ask_question_tool via sync ToolNode path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from langchain_core.messages import ToolMessage


class SyncHookParityAdapter(AgentMiddleware):  # type: ignore[type-arg]
    """Passthrough sync hooks for middleware that only define async variants."""

    def __init__(self, inner: AgentMiddleware) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(
            self,
            "_parity_name",
            getattr(inner, "name", type(inner).__name__),
        )

    @property
    def name(self) -> str:
        return str(object.__getattribute__(self, "_parity_name"))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[object]],
    ) -> ToolMessage | Command[object]:
        return handler(request)

    def wrap_model_call(
        self,
        request: ModelRequest[object],
        handler: Callable[[ModelRequest[object]], ModelResponse[object]],
    ) -> ModelResponse[object]:
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[object],
        handler: Callable[[ModelRequest[object]], Awaitable[ModelResponse[object]]],
    ) -> ModelResponse[object]:
        inner = object.__getattribute__(self, "_inner")
        if type(inner).awrap_model_call is AgentMiddleware.awrap_model_call:
            return await handler(request)
        return await inner.awrap_model_call(request, handler)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[object]]],
    ) -> ToolMessage | Command[object]:
        inner = object.__getattribute__(self, "_inner")
        if type(inner).awrap_tool_call is AgentMiddleware.awrap_tool_call:
            return await handler(request)
        return await inner.awrap_tool_call(request, handler)

    async def aafter_model(
        self, state: dict[str, object], runtime: object
    ) -> dict[str, object] | None:
        inner = object.__getattribute__(self, "_inner")
        if type(inner).aafter_model is AgentMiddleware.aafter_model:
            return None
        return await inner.aafter_model(state, runtime)

    def __getattr__(self, name: str) -> object:
        return getattr(object.__getattribute__(self, "_inner"), name)


def _uses_default_sync_tool_hook(middleware: AgentMiddleware) -> bool:
    return type(middleware).wrap_tool_call is AgentMiddleware.wrap_tool_call


def _uses_default_sync_model_hook(middleware: AgentMiddleware) -> bool:
    inner = middleware
    if isinstance(middleware, SyncHookParityAdapter):
        inner = object.__getattribute__(middleware, "_inner")
    cls = type(inner)
    has_async_model = cls.awrap_model_call is not AgentMiddleware.awrap_model_call
    has_sync_model = cls.wrap_model_call is not AgentMiddleware.wrap_model_call
    return has_async_model and not has_sync_model


def apply_sync_hook_parity(middlewares: list[object]) -> list[object]:
    """Wrap middlewares missing sync hooks so sync ToolNode paths do not raise."""
    adapted: list[object] = []
    for middleware in middlewares:
        if not isinstance(middleware, AgentMiddleware):
            adapted.append(middleware)
            continue
        if isinstance(middleware, SyncHookParityAdapter):
            adapted.append(middleware)
            continue
        needs_tool = _uses_default_sync_tool_hook(middleware)
        needs_model = _uses_default_sync_model_hook(middleware)
        if needs_tool or needs_model:
            adapted.append(SyncHookParityAdapter(middleware))
        else:
            adapted.append(middleware)
    return adapted


__all__ = ["SyncHookParityAdapter", "apply_sync_hook_parity"]
