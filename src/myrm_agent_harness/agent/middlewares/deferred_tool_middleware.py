"""Deferred tool middleware.

[INPUT]
- agent.tool_management.registry::ToolRegistry (POS: Tool registry)
- langchain.agents.middleware::AgentMiddleware (POS: Middleware base)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: Tool execution request for interceptors)

[OUTPUT]
- DeferredToolMiddleware: supplies DISCOVERABLE tools at ToolNode execution via awrap_tool_call;
  skill schema attenuation on model requests.

[POS]
Middleware for deferred native tools. Does not mutate ``request.tools`` (prefix-cache safe).
``invoke_deferred_tool`` is the primary activation path; awrap_tool_call still resolves
direct deferred tool names dynamically for ToolNode.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry

logger = logging.getLogger(__name__)


class DeferredToolMiddleware(AgentMiddleware[Any, Any, Any]):
    """Runtime resolution for DISCOVERABLE tools without bind_tools schema injection."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | Any:
        raise NotImplementedError("DeferredToolMiddleware does not support synchronous wrap_model_call")

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        from myrm_agent_harness.agent._skill_agent_context import get_loaded_skills
        from myrm_agent_harness.agent.skills.runtime.attenuator import attenuate_tools

        loaded_skills = get_loaded_skills()
        if loaded_skills and request.tools:
            tool_names: list[str] = []
            for tool in request.tools:
                name = tool.name if hasattr(tool, "name") else tool.get("name")
                if name:
                    tool_names.append(str(name))

            attenuation = attenuate_tools(tool_names, loaded_skills)
            allowed_names = frozenset(attenuation.tool_names)
            if attenuation.removed_tools:
                request.tools = [
                    tool
                    for tool in request.tools
                    if (tool.name if hasattr(tool, "name") else tool.get("name")) in allowed_names
                ]
                logger.info(
                    " DeferredToolMiddleware schema filter removed %d tool(s): %s",
                    len(attenuation.removed_tools),
                    attenuation.removed_tools,
                )

        return await handler(request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        raise NotImplementedError("DeferredToolMiddleware does not support synchronous wrap_tool_call")

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """Provide deferred BaseTool instances for ToolNode (dynamic tools)."""
        if request.tool is not None:
            return await handler(request)

        from myrm_agent_harness.agent.middlewares._session_context import (
            get_active_resolved_tools,
            get_active_tool_registry,
        )

        registry = get_active_tool_registry() or self.registry
        resolved_tools = get_active_resolved_tools()

        call_name = str(request.tool_call.get("name", ""))
        candidate_names = {call_name}
        if not call_name.endswith("_tool"):
            candidate_names.add(f"{call_name}_tool")
        else:
            candidate_names.add(call_name.removesuffix("_tool"))

        search_pool: list[object] = []
        if resolved_tools:
            search_pool.extend(resolved_tools)
        search_pool.extend(registry.resolve())
        search_pool.extend(registry.get_runtime_tools())

        seen: set[str] = set()
        for resolved_tool in search_pool:
            name = getattr(resolved_tool, "name", None)
            if not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            if name in candidate_names:
                return await handler(request.override(tool=resolved_tool))

        for dt in registry.get_discoverable_tools():
            if dt.name in candidate_names:
                return await handler(request.override(tool=dt))

        return await handler(request)
