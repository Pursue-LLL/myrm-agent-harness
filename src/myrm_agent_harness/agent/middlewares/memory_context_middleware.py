"""Memory context injection middleware.

Hybrid instruction hierarchy with cold/warm adaptive prompt:

- Stable / high-privilege layer: Profile, Self-Instructions, Behavioral Rules + Corrections
  → wrapped in ``<user_memory_context>``, injected as SystemMessage immediately after leading
    System prompts (prompt-cache friendly).

- Untrusted learned layer: auto-extracted Preferences + Learned Rules
  → wrapped with ``wrap_untrusted(..., source="memory_context")`` (`<<<UNTRUSTED_DATA id="…">>`)
    so it aligns with SECURITY_BOUNDARY_SYSTEM_RULES.

- Cold start: Discovery Mode lives only in `<user_memory_context>` (still SystemMessage).

Respects RecallMode: TOOLS skips injection entirely.
Injection is one-shot: detected via ``<user_memory_context`` OR ``<<<UNTRUSTED_DATA``.

Design message order:

    System Prompt (cross-user stable) …
    <user_instructions> …
    <user_memory_context> … stable profile / rules …
    HumanMessage with <<<UNTRUSTED_DATA learned …>>>  + Memory Search cues
    first real user HumanMessage …

[INPUT]
- toolkits.memory.config::RecallMode (POS: Memory configuration — functional switches and retrieval params only.)
- toolkits.memory.manager::MemoryManager (POS: Unified memory manager and core facade of the Memory Toolkit. Orchestrates all memory operations via pure dependency injection — no concrete backends, only protocols.)
- agent.security.guards.prompt_budget::BudgetedSection, CHARS_PER_TOKEN (POS: Prompt Budget Guard — section budgets for dynamic injection.)
- agent.security.detection.content_boundary::sanitize, wrap_untrusted (POS: Untrusted content folding, marker neutralization, randomized UNTRUSTED_DATA envelopes.)

[OUTPUT]
- memory_context_middleware: AgentMiddleware — stable + learned memory injection with unified budget and idempotent markers.

[POS]
Memory context injection middleware bridging MemoryManager snapshots into the model prefix with privilege separation for learned content.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.memory.config import RecallMode

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

from .memory_context_format import (
    MEMORY_CONTEXT_MARKER,
    MEMORY_UNTRUSTED_OPEN_MARKER,
    _COLD_START_CONTEXT,
    _conversation_search_tool_bound,
    _escape_xml_item,
    _format_memory_context,
    _has_memory_context,
    _partition_budget_sections,
)

__all__ = [
    "MEMORY_CONTEXT_MARKER",
    "MEMORY_UNTRUSTED_OPEN_MARKER",
    "_COLD_START_CONTEXT",
    "_escape_xml_item",
    "_format_memory_context",
    "_has_memory_context",
    "_partition_budget_sections",
    "MemoryContextMiddleware",
    "memory_context_middleware",
]

class MemoryContextMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Inject user memory context on first LLM call.

    Stable context is appended as ``SystemMessage`` after leading systems; learned
    context is appended as ``HumanMessage`` with ``<<<UNTRUSTED_DATA>>>`` framing
    before the user's first HumanMessage.

    Requires context key: "memory_manager" (MemoryManager with user_id bound).
    """

    name = "memory_context_middleware"

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        import copy

        from langchain_core.messages import AIMessage

        new_req_messages = []
        req_modified = False
        for msg in request.messages:
            if isinstance(msg, AIMessage) and getattr(msg, "name", None):
                prefix = f"[Agent: {msg.name}]\n"
                if isinstance(msg.content, str) and not msg.content.startswith(prefix):
                    new_msg = AIMessage(
                        content=f"{prefix}{msg.content}",
                        name=msg.name,
                        tool_calls=getattr(msg, "tool_calls", []),
                        additional_kwargs=getattr(msg, "additional_kwargs", {}),
                        id=getattr(msg, "id", None),
                    )
                    new_req_messages.append(new_msg)
                    req_modified = True
                    continue
                elif isinstance(msg.content, list) and len(msg.content) > 0 and msg.content[0].get("type") == "text":
                    first_text = msg.content[0].get("text", "")
                    if not first_text.startswith(prefix):
                        new_content = copy.deepcopy(msg.content)
                        new_content[0]["text"] = f"{prefix}{first_text}"
                        new_msg = AIMessage(
                            content=new_content,
                            name=msg.name,
                            tool_calls=getattr(msg, "tool_calls", []),
                            additional_kwargs=getattr(msg, "additional_kwargs", {}),
                            id=getattr(msg, "id", None),
                        )
                        new_req_messages.append(new_msg)
                        req_modified = True
                        continue
            new_req_messages.append(msg)

        if req_modified:
            request = request.override(messages=new_req_messages)

        state = request.state
        state_messages = state.get("messages", [])

        if _has_memory_context(state_messages) or _has_memory_context(request.messages):
            return await handler(request)

        context = getattr(request.runtime, "context", None) if request.runtime else None
        if not context:
            return await handler(request)

        from myrm_agent_harness.agent._skill_agent_context import get_memory_manager

        manager: MemoryManager | None = get_memory_manager()
        if not manager:
            return await handler(request)

        if manager.recall_mode == RecallMode.TOOLS:
            return await handler(request)

        try:
            static_result, learned_result = await asyncio.gather(
                manager.get_context(include_profile=True, include_rules=True, include_agent_instructions=True),
                manager.get_learned_context(),
                return_exceptions=True,
            )
        except Exception as e:
            logger.warning("Failed to load memory context: %s", e)
            return await handler(request)

        if isinstance(static_result, BaseException):
            logger.warning("Static memory context failed: %s", static_result)
            return await handler(request)
        memory_ctx: dict[str, object] = static_result

        if isinstance(learned_result, BaseException):
            logger.warning("Learned memory context failed (non-fatal): %s", learned_result)
            learned_ctx: dict[str, list[dict[str, str]]] = {"learned_rules": [], "learned_preferences": []}
        else:
            learned_ctx = learned_result

        include_conversation_search = _conversation_search_tool_bound(request)
        stable_formatted, untrusted_formatted = _format_memory_context(
            memory_ctx,
            learned_ctx,
            include_conversation_search=include_conversation_search,
        )
        if not stable_formatted and not untrusted_formatted:
            return await handler(request)

        new_messages = list(request.messages)

        if stable_formatted:
            stable_msg = SystemMessage(content=stable_formatted)
            # Insert after the last SystemMessage to maintain Prefix Cache
            insert_idx_stable = 0
            for i, msg in enumerate(new_messages):
                if isinstance(msg, SystemMessage):
                    insert_idx_stable = i + 1
                else:
                    break
            new_messages.insert(insert_idx_stable, stable_msg)
            state_messages.insert(insert_idx_stable, stable_msg)

        if untrusted_formatted:
            untrusted_msg = HumanMessage(content=untrusted_formatted)
            # Insert before the first HumanMessage
            insert_idx_untrusted = len(new_messages)
            for i, msg in enumerate(new_messages):
                if isinstance(msg, HumanMessage):
                    insert_idx_untrusted = i
                    break
            new_messages.insert(insert_idx_untrusted, untrusted_msg)
            state_messages.insert(insert_idx_untrusted, untrusted_msg)

        n_rules = len(learned_ctx.get("learned_rules", []))
        n_prefs = len(learned_ctx.get("learned_preferences", []))
        is_cold = stable_formatted is not None and "Discovery Mode" in stable_formatted

        # Expose memory budget to the runner state for UX progress bars (Item 7)
        if hasattr(manager, "_config"):
            base_budget = manager._config.max_learned_context_chars
            if manager._config.model_context_tokens:
                total_budget = max(base_budget, manager._config.model_context_tokens // 30)
            else:
                total_budget = base_budget
            used_chars = len(stable_formatted or "") + len(untrusted_formatted or "")
            state["memory_budget_used"] = used_chars
            state["memory_budget_total"] = total_budget

            # Also store it on the manager for easy extraction in finalize_agent_stream_session
            manager._last_budget = {"used": used_chars, "total": total_budget}

        logger.info(
            "Memory context injected for user %s: cold=%s, %d learned rules, %d learned preferences",
            manager.user_id,
            is_cold,
            n_rules,
            n_prefs,
        )

        return await handler(request.override(messages=new_messages))


memory_context_middleware = MemoryContextMiddleware()
