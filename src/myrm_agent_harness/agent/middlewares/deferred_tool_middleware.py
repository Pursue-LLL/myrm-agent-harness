"""Deferred tool middleware.

[INPUT]
- agent.tool_management.registry::ToolRegistry (POS: Tool registry)
- langchain.agents.middleware::AgentMiddleware (POS: Middleware base)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: Tool execution request for interceptors)

[OUTPUT]
- DeferredToolMiddleware: Injects dynamically activated deferred tools into model bind_tools
  and supplies BaseTool instances at ToolNode execution via awrap_tool_call.

[POS]
Middleware that scans chat history for discover_capability outputs and dynamically
activates deferred tools: augments ModelRequest.tools for the LLM and uses
ToolCallRequest.override(tool=...) so LangGraph ToolNode can execute tools not
present at graph compile time (see LangChain DYNAMIC_TOOL_ERROR_TEMPLATE).
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
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    CONVERSATION_SEARCH_TOOL_NAME,
)

logger = logging.getLogger(__name__)

_DISCOVER_TOOL_MESSAGE_NAMES = frozenset(
    {"discover_capability", "discover_capability_tool"}
)  # TODO(2026-Q3): remove "discover_capability" legacy alias after migration settles

# User asks for verbatim / cross-chat evidence — pre-mount conversation_search without a discover LLM turn.
_VERBATIM_CONVERSATION_INTENT_RE = re.compile(
    r"(?:"
    r"原文|原话|"
    r"哪(?:一)?次(?:聊天|对话|会话)|"
    r"历史(?:聊天|对话|会话|记录)|"
    r"聊天记录|"
    r"chat\s*history|"
    r"(?:which|what|where).*(?:conversation|chat|session)|"
    r"(?:conversation|chat|session).*(?:mentioned|said|discussed)|"
    r"(?:search|find|look\s+up).*(?:conversation|chat|session)|"
    r"conversation[_\s-]*search|"
    r"(?:之前|以前|上周|上次).*(?:聊|对话|说过)"
    r")",
    re.IGNORECASE,
)

_CONTINUE_ONLY_RE = re.compile(
    r"^(?:继续|接着|continue(?:\s+where|\s+from)?)\b",
    re.IGNORECASE,
)


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


def collect_activated_native_tool_names(messages: list[AnyMessage]) -> set[str]:
    """Parse discover_capability ToolMessages for <AutoMountTools> native tool names."""
    activated: set[str] = set()
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


def _last_human_message_text(messages: list[AnyMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                return " ".join(parts).strip()
    return ""


def detect_verbatim_conversation_search_intent(text: str) -> bool:
    """True when the user likely needs FTS conversation evidence, not semantic recall alone."""
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    if not _VERBATIM_CONVERSATION_INTENT_RE.search(stripped):
        return False
    if _CONTINUE_ONLY_RE.search(stripped) and not re.search(
        r"历史|哪次|原文|previous|past|conversation\s*search",
        stripped,
        re.IGNORECASE,
    ):
        return False
    return True


def collect_deferred_premount_tool_names(
    messages: list[AnyMessage],
    deferred_tool_names: frozenset[str],
) -> set[str]:
    """Deterministic pre-mount for deferred tools (no discover LLM turn)."""
    if CONVERSATION_SEARCH_TOOL_NAME not in deferred_tool_names:
        return set()
    query = _last_human_message_text(messages)
    if detect_verbatim_conversation_search_intent(query):
        return {CONVERSATION_SEARCH_TOOL_NAME}
    return set()


def collect_all_activated_deferred_tool_names(
    messages: list[AnyMessage],
    deferred_tool_names: frozenset[str],
) -> set[str]:
    return collect_activated_native_tool_names(messages) | collect_deferred_premount_tool_names(
        messages, deferred_tool_names
    )


class DeferredToolMiddleware(AgentMiddleware[Any, Any, Any]):
    """Activates deferred tools after discover_capability exposes <AutoMountTools>.

    - ``awrap_model_call``: appends activated deferred ``BaseTool`` instances to
      ``request.tools`` so the model can emit tool_calls for them.
    - ``awrap_tool_call``: when ToolNode has no ``BaseTool`` for that name (dynamic tool),
      supplies the deferred tool via ``request.override(tool=...)`` so execution succeeds.
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
        deferred_tools = self.registry.get_deferred_tools()
        deferred_tool_names = frozenset(
            name for tool in deferred_tools if isinstance(name := getattr(tool, "name", None), str)
        )
        activated_tool_names = collect_all_activated_deferred_tool_names(
            request.messages, deferred_tool_names
        )

        if activated_tool_names:
            existing_tool_names = {t.name if hasattr(t, "name") else t.get("name") for t in request.tools}

            added_count = 0
            for tool in deferred_tools:
                if tool.name in activated_tool_names and tool.name not in existing_tool_names:
                    request.tools.append(tool)
                    added_count += 1

            if added_count > 0:
                logger.info(
                    " DeferredToolMiddleware dynamically activated %d tools: %s",
                    added_count,
                    sorted(activated_tool_names),
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
        deferred_tool_names = frozenset(
            name for dt in registry.get_deferred_tools() if isinstance(name := getattr(dt, "name", None), str)
        )
        activated = collect_all_activated_deferred_tool_names(messages, deferred_tool_names)
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
        search_pool.extend(registry.get_deferred_tools())

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

        for dt in registry.get_deferred_tools():
            if dt.name in candidate_names:
                return await handler(request.override(tool=dt))

        return await handler(request)
