"""Deferred tools stable index injection middleware.

[POS]
Injects ``<available-deferred-tools>`` once per thread via stable_index helpers;
does not mutate ``request.tools`` (see tool_management/defer/_ARCH.md).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from myrm_agent_harness.agent.tool_management.defer.stable_index import (
    DEFERRED_TOOLS_MARKER,
    build_deferred_tools_prompt_section,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _has_deferred_index(messages: list[object]) -> bool:
    for msg in messages[:12]:
        if isinstance(msg, SystemMessage):
            content = msg.content
            if isinstance(content, str) and DEFERRED_TOOLS_MARKER in content:
                return True
    return False


def _find_system_insert_idx(messages: list[object]) -> int:
    idx = 0
    for i, msg in enumerate(messages):
        if isinstance(msg, SystemMessage):
            idx = i + 1
        else:
            break
    return idx


class DeferredIndexMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Inject ``<available-deferred-tools>`` once per thread (stable system prefix)."""

    name = "deferred_index_middleware"

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        raise NotImplementedError("DeferredIndexMiddleware does not support synchronous wrap_model_call")

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        deferred_names = [t.name for t in self._registry.get_discoverable_tools()]
        section = build_deferred_tools_prompt_section(deferred_names)
        if not section:
            return await handler(request)

        if _has_deferred_index(list(request.messages)):
            return await handler(request)

        state_messages = request.state.get("messages", []) if request.state else []
        if isinstance(state_messages, list) and _has_deferred_index(state_messages):
            return await handler(request)

        new_messages = list(request.messages)
        insert_idx = _find_system_insert_idx(new_messages)
        new_messages.insert(insert_idx, SystemMessage(content=section))
        request = request.override(messages=new_messages)
        logger.info(
            "Injected deferred tools index (%d tools) at position %d",
            len(deferred_names),
            insert_idx,
        )
        return await handler(request)
