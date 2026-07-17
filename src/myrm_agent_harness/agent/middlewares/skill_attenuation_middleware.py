"""Skill attenuation and dynamic tool resolution middleware.

[INPUT]
- agent.tool_management.registry::ToolRegistry (POS: Tool registry)
- agent.middlewares._skill_tool_choice (POS: Skill attenuation request metadata builder)
- langchain.agents.middleware::AgentMiddleware (POS: Middleware base)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: Tool execution request for interceptors)

[OUTPUT]
- SkillAttenuationMiddleware: applies skill attenuation via ``tool_choice.allowed_tools``
  and resolves dynamic tools at ToolNode execution time.

[POS]
Skill attenuation uses per-turn ``tool_choice`` (OpenAI ``allowed_tools`` mode) so the
bound tools prefix stays cache-stable. Execution-layer enforcement remains in
``check_trust_attenuation`` via tool_interceptor.
``awrap_tool_call`` resolves tools for ToolNode when ``request.tool is None``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SkillAttenuationMiddleware(AgentMiddleware[AgentState[object], object, object]):
    """Apply skill attenuation and resolve dynamic tools without mutating ``bind_tools``."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def wrap_model_call(
        self,
        request: ModelRequest[object],
        handler: Callable[[ModelRequest[object]], ModelResponse[object]],
    ) -> ModelResponse[object]:
        raise NotImplementedError("SkillAttenuationMiddleware does not support synchronous wrap_model_call")

    async def awrap_model_call(
        self,
        request: ModelRequest[object],
        handler: Callable[[ModelRequest[object]], Awaitable[ModelResponse[object]]],
    ) -> ModelResponse[object]:
        from myrm_agent_harness.agent._skill_agent_context import get_loaded_skills
        from myrm_agent_harness.agent.middlewares._skill_tool_choice import (
            build_allowed_tools_tool_choice,
            extract_bound_tool_names,
        )
        from myrm_agent_harness.agent.skills.runtime.attenuator import attenuate_tools

        loaded_skills = get_loaded_skills()
        if loaded_skills and request.tools:
            tool_names = extract_bound_tool_names(list(request.tools))
            attenuation = attenuate_tools(tool_names, loaded_skills)
            if attenuation.removed_tools:
                allowed_names = frozenset(attenuation.tool_names)
                request = request.override(
                    tool_choice=build_allowed_tools_tool_choice(allowed_names),
                )
                logger.info(
                    " SkillAttenuationMiddleware allowed_tools restricted %d tool(s): %s",
                    len(attenuation.removed_tools),
                    attenuation.removed_tools,
                )

        return await handler(request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[object]],
    ) -> ToolMessage | Command[object]:
        raise NotImplementedError("SkillAttenuationMiddleware does not support synchronous wrap_tool_call")

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[object]]],
    ) -> ToolMessage | Command[object]:
        """Resolve dynamic BaseTool instances for ToolNode when not pre-bound."""
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

        return await handler(request)
