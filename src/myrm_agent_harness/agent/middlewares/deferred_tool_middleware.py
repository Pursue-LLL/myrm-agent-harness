"""Deferred tool middleware.

[INPUT]
- agent.tool_management.registry::ToolRegistry (POS: Tool registry)
- langchain.agents.middleware::AgentMiddleware (POS: Middleware base)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: Tool execution request for interceptors)

[OUTPUT]
- DeferredToolMiddleware: AutoMount discoverable tools into model bind_tools
  and supplies BaseTool instances at ToolNode execution via awrap_tool_call.

[POS]
Middleware that scans chat history for discover_capability outputs and dynamically
activates discoverable tools (``ToolBindMode.DISCOVERABLE``): augments ModelRequest.tools
for the LLM and uses ToolCallRequest.override(tool=...) so LangGraph ToolNode can execute
tools not present at graph compile time (see LangChain DYNAMIC_TOOL_ERROR_TEMPLATE).
``RUNTIME_ONLY`` tools are executable via awrap_tool_call but never AutoMount.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AnyMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.meta_tools.bash.background_deferred_activation import (
    get_session_deferred_tool_names,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry

logger = logging.getLogger(__name__)

_DISCOVER_TOOL_MESSAGE_NAMES = frozenset(
    {"discover_capability", "discover_capability_tool"}
)  # TODO(2026-Q3): remove "discover_capability" legacy alias after migration settles


def _is_discover_capability_tool_message(name: str | None) -> bool:
    """Match ToolMessage.name for the discovery meta-tool (raw and _tool-suffixed)."""
    return bool(name) and name in _DISCOVER_TOOL_MESSAGE_NAMES


def _messages_from_agent_state(state: object) -> list[AnyMessage]:
    if isinstance(state, dict):
        raw = state.get("messages")
        if isinstance(raw, list):
            return list(raw)
        return []
    messages_attr = getattr(state, "messages", None)
    if isinstance(messages_attr, list):
        return list(messages_attr)
    return []


def collect_activated_native_tool_names(
    messages: list[AnyMessage],
    *,
    session_id: str = "",
) -> set[str]:
    """Parse discover_capability ToolMessages and session spawn AutoMount names."""
    activated: set[str] = set()
    if session_id:
        activated |= set(get_session_deferred_tool_names(session_id))
    for msg in messages:
        if not isinstance(msg, ToolMessage) or not _is_discover_capability_tool_message(msg.name):
            continue
        try:
            content = str(msg.content)
            match = re.search(
                r"<AutoMountTools>\s*(\[.*?\])\s*</AutoMountTools>",
                content,
                re.DOTALL,
            )
            if not match:
                continue
            json_str = match.group(1)
            matches = json.loads(json_str)
            for m in matches:
                if isinstance(m, dict) and "name" in m:
                    activated.add(str(m["name"]))
        except Exception as e:
            logger.debug("Failed to parse discover_capability output: %s", e)
    return activated


class DeferredToolMiddleware(AgentMiddleware[Any, Any, Any]):
    """Activates discoverable tools after discover_capability exposes <AutoMountTools>.

    - ``awrap_model_call``: appends activated discoverable ``BaseTool`` instances to
      ``request.tools`` so the model can emit tool_calls for them.
    - ``awrap_tool_call``: when ToolNode has no ``BaseTool`` for that name (dynamic tool),
      supplies discoverable or runtime-only tools via ``request.override(tool=...)``.
    """

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
        discoverable_tools = self.registry.get_discoverable_tools()
        from myrm_agent_harness.agent.middlewares._session_context import get_approval_session

        session_id = get_approval_session()
        activated_tool_names = collect_activated_native_tool_names(
            request.messages,
            session_id=session_id,
        )

        if activated_tool_names:
            existing_tool_names = {t.name if hasattr(t, "name") else t.get("name") for t in request.tools}

            added_count = 0
            for tool in discoverable_tools:
                if tool.name in activated_tool_names and tool.name not in existing_tool_names:
                    request.tools.append(tool)
                    added_count += 1

            if added_count > 0:
                logger.info(
                    " DeferredToolMiddleware dynamically activated %d tools: %s",
                    added_count,
                    sorted(activated_tool_names),
                )

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

        messages = _messages_from_agent_state(request.state)
        from myrm_agent_harness.agent.middlewares._session_context import get_approval_session

        session_id = get_approval_session()
        activated = collect_activated_native_tool_names(messages, session_id=session_id)
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

        if call_name not in activated:
            seen: set[str] = set()
            for resolved_tool in search_pool:
                name = getattr(resolved_tool, "name", None)
                if not isinstance(name, str) or name in seen:
                    continue
                seen.add(name)
                if name in candidate_names:
                    return await handler(request.override(tool=resolved_tool))

            return await handler(request)

        for dt in registry.get_discoverable_tools():
            if dt.name in candidate_names:
                return await handler(request.override(tool=dt))

        return await handler(request)
