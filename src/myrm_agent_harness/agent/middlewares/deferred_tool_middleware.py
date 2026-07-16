"""Deferred tool middleware.

[INPUT]
- agent.tool_management.registry::ToolRegistry (POS: Tool registry)
- agent.middlewares._skill_tool_choice (POS: Skill attenuation request metadata builder)
- langchain.agents.middleware::AgentMiddleware (POS: Middleware base)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: Tool execution request for interceptors)

[OUTPUT]
- DeferredToolMiddleware: normalizes ``invoke_deferred_tool`` calls to their effective
  identity before after-model policies, supplies DISCOVERABLE tools at ToolNode execution,
  and applies skill attenuation via ``tool_choice.allowed_tools``.

[POS]
Middleware for deferred native tools. Does not mutate ``request.tools`` (prefix-cache safe).
Skill attenuation uses per-turn ``tool_choice`` (OpenAI ``allowed_tools`` mode) so the
bound tools prefix stays cache-stable. Execution-layer enforcement remains in
``check_trust_attenuation`` via tool_interceptor.
``invoke_deferred_tool`` is a schema-only activation gateway. Its calls are rewritten to
the canonical deferred target before approval, so every downstream policy observes the
effective tool name and arguments. ``awrap_tool_call`` resolves that target for ToolNode.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    Runtime,
)
from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langchain_core.messages.tool import tool_call
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.meta_tools.defer.invoke_deferred_tool import (
    INVOKE_DEFERRED_TOOL_NAME,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry

logger = logging.getLogger(__name__)


class DeferredToolMiddleware(AgentMiddleware[AgentState[object], object, object]):
    """Normalize and resolve deferred tools without mutating ``bind_tools``."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def wrap_model_call(
        self,
        request: ModelRequest[object],
        handler: Callable[[ModelRequest[object]], ModelResponse[object]],
    ) -> ModelResponse[object]:
        raise NotImplementedError("DeferredToolMiddleware does not support synchronous wrap_model_call")

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
                    " DeferredToolMiddleware allowed_tools restricted %d tool(s): %s",
                    len(attenuation.removed_tools),
                    attenuation.removed_tools,
                )

        return await handler(request)

    async def aafter_model(
        self,
        state: AgentState[object],
        runtime: Runtime[object],
    ) -> dict[str, object] | None:
        """Rewrite valid gateway calls before approval and other after-model policies."""
        del runtime
        messages = state.get("messages", [])
        last_ai_message = next((message for message in reversed(messages) if isinstance(message, AIMessage)), None)
        if last_ai_message is None or not last_ai_message.tool_calls:
            return None

        normalized_calls: list[ToolCall] = []
        changed = False
        for current_call in last_ai_message.tool_calls:
            normalized_call = self._normalize_gateway_call(current_call)
            normalized_calls.append(normalized_call)
            changed = changed or normalized_call is not current_call

        if not changed:
            return None

        last_ai_message.tool_calls = normalized_calls
        logger.info(
            "Normalized %d deferred gateway call(s)",
            sum(call["name"] != INVOKE_DEFERRED_TOOL_NAME for call in normalized_calls),
        )
        return {"messages": [last_ai_message]}

    def _normalize_gateway_call(self, current_call: ToolCall) -> ToolCall:
        """Return an effective ToolCall, or the original gateway call on invalid input."""
        if current_call.get("name") != INVOKE_DEFERRED_TOOL_NAME:
            return current_call

        raw_outer_arguments: object = current_call.get("args")
        if not isinstance(raw_outer_arguments, dict):
            logger.warning("Refused malformed deferred gateway call: args must be an object")
            return current_call

        raw_target_name: object = raw_outer_arguments.get("name")
        raw_target_arguments: object = raw_outer_arguments.get("arguments", {})
        if not isinstance(raw_target_name, str) or not raw_target_name:
            logger.warning("Refused malformed deferred gateway call: target name is missing")
            return current_call
        if raw_target_name == INVOKE_DEFERRED_TOOL_NAME:
            logger.warning("Refused nested deferred gateway call")
            return current_call
        if not isinstance(raw_target_arguments, dict):
            logger.warning(
                "Refused malformed deferred gateway call for %r: arguments must be an object", raw_target_name
            )
            return current_call

        target = next(
            (tool for tool in self.registry.get_discoverable_tools() if tool.name == raw_target_name),
            None,
        )
        if target is None:
            logger.warning("Refused deferred gateway target outside the discoverable catalog: %r", raw_target_name)
            return current_call

        target_arguments: dict[str, object] = {}
        for key, value in raw_target_arguments.items():
            if not isinstance(key, str):
                logger.warning("Refused deferred gateway call for %r: argument keys must be strings", raw_target_name)
                return current_call
            target_arguments[key] = value

        return tool_call(
            name=target.name,
            args=target_arguments,
            id=current_call.get("id"),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[object]],
    ) -> ToolMessage | Command[object]:
        raise NotImplementedError("DeferredToolMiddleware does not support synchronous wrap_tool_call")

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[object]]],
    ) -> ToolMessage | Command[object]:
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
