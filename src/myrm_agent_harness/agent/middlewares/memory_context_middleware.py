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
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.security.detection.content_boundary import sanitize, wrap_untrusted
from myrm_agent_harness.agent.security.guards.prompt_budget import (
    CHARS_PER_TOKEN,
    BudgetedSection,
)
from myrm_agent_harness.toolkits.memory.config import RecallMode

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

MEMORY_CONTEXT_MARKER = "<user_memory_context"

# Wrapped learned memory — must participate in injection idempotency (learned-only path has no `<user_memory_context`).
MEMORY_UNTRUSTED_OPEN_MARKER = "<<<UNTRUSTED_DATA"


def _has_memory_context(messages: Sequence[BaseMessage]) -> bool:
    for msg in messages[:15]:
        if isinstance(msg, (SystemMessage, HumanMessage)):
            content = msg.content
            if not isinstance(content, str):
                continue
            if MEMORY_CONTEXT_MARKER in content or MEMORY_UNTRUSTED_OPEN_MARKER in content:
                return True
    return False


def _escape_xml_item(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _partition_budget_sections(
    stable_sections: list[BudgetedSection],
    escaped_untrusted_sections: list[BudgetedSection],
    *,
    max_tokens: int,
    truncation_message: str,
) -> tuple[str, str]:
    """Apply a single combined char budget; split Markdown body into stable vs untrusted halves.

    Mirrors ``PromptBudgetGuard.apply_budget`` priority ordering across both buckets so total
    memory injection cannot exceed historical single-guard semantics.
    """
    tagged: list[tuple[str, BudgetedSection]] = [("stable", s) for s in stable_sections]
    tagged.extend(("untrusted", s) for s in escaped_untrusted_sections)
    tagged.sort(key=lambda t: t[1].priority)

    max_chars = max_tokens * CHARS_PER_TOKEN
    current_length = 0
    truncated = False

    stable_blocks: list[str] = []
    untrusted_blocks: list[str] = []

    for kind, section in tagged:
        if not section.items:
            continue
        header = f"## {section.title}\n"
        if current_length + len(header) > max_chars:
            truncated = True
            break
        current_length += len(header)

        accepted_lines: list[str] = []
        for item in section.items:
            line = f"- {item}\n"
            if current_length + len(line) > max_chars:
                truncated = True
                break
            accepted_lines.append(line)
            current_length += len(line)

        if not accepted_lines:
            continue

        block = header + "".join(accepted_lines).strip()
        if kind == "stable":
            stable_blocks.append(block)
        else:
            untrusted_blocks.append(block)

        if truncated:
            break

    stable_body = "\n\n".join(stable_blocks).strip()
    untrusted_body = "\n\n".join(untrusted_blocks).strip()

    if truncated and truncation_message:
        trimmed = truncation_message.strip()
        if untrusted_blocks:
            untrusted_body = f"{untrusted_body}\n{trimmed}" if untrusted_body else trimmed
        elif stable_blocks:
            stable_body = f"{stable_body}\n{trimmed}" if stable_body else trimmed

    return stable_body, untrusted_body


def _format_memory_context(ctx: dict[str, object], learned: dict[str, list[dict[str, str]]]) -> tuple[str | None, str | None]:
    stable_sections: list[BudgetedSection] = []
    untrusted_sections: list[BudgetedSection] = []

    # ── Stable Layer (High Privilege): user-configured, rarely changes ──
    global_profile = dict(ctx.get("global_profile", {}))
    if global_profile:
        items = [f"{k}: {v}" for k, v in global_profile.items()]
        if items:
            stable_sections.append(BudgetedSection("Global User Profile", items, priority=1))

    peer_profile = dict(ctx.get("peer_profile", {}))
    peer_items = [f"{k}: {v}" for k, v in peer_profile.items()] if peer_profile else []


    if peer_items:
        stable_sections.append(BudgetedSection("Our Relationship & Your Persona", peer_items, priority=1))

    instructions = ctx.get("agent_instructions", [])
    if instructions and isinstance(instructions, list):
        items = [f"{i['instruction']}" for i in instructions if isinstance(i, dict)]
        if items:
            stable_sections.append(BudgetedSection("Your Self-Instructions", items, priority=2))

    rules = ctx.get("rules", [])
    if rules and isinstance(rules, list):
        items = [f"When: {r['trigger']} → Do: {r['action']}" for r in rules if isinstance(r, dict)]
        if items:
            stable_sections.append(BudgetedSection("Behavioral Rules", items, priority=3))

    # ── Learned Layer (Low Privilege / Untrusted): auto-extracted, evolves across sessions ──
    learned_prefs = learned.get("learned_preferences", [])
    if learned_prefs:
        corrections: list[str] = []
        preferences: list[str] = []
        for p in learned_prefs:
            safe_content = sanitize(p["content"])
            # Format the created_at timestamp if present to provide age context
            created_at = p.get("created_at")
            time_prefix = f"[Created: {created_at[:10]}] " if created_at else ""
            
            mem_id = p.get("id", "")
            id_label = f" [ID: {mem_id}]" if mem_id else ""
            
            if p.get("source_error"):
                corrections.append(f"{time_prefix}{safe_content} — AVOID: {sanitize(p['source_error'])}{id_label}")
            else:
                preferences.append(f"{time_prefix}{safe_content}{id_label}")
        if corrections:
            # Corrections are user-explicit feedback → belongs in Stable layer
            stable_sections.append(BudgetedSection("Corrections (must follow)", corrections, priority=4))
        if preferences:
            untrusted_sections.append(BudgetedSection("Learned Preferences (from past interactions)", preferences, priority=6))

    learned_rules = learned.get("learned_rules", [])
    if learned_rules:
        critical_items: list[str] = []
        normal_items: list[str] = []
        for r in learned_rules:
            tool_priority = r.get("tool_rule_priority", "normal")
            tool_name = r.get("tool_name", "")
            tool_label = f" [{tool_name}]" if tool_name else ""
            created_at = r.get("created_at")
            time_prefix = f"[Created: {created_at[:10]}] " if created_at else ""
            
            mem_id = r.get("id", "")
            id_label = f" [ID: {mem_id}]" if mem_id else ""
            
            formatted = f"{time_prefix}When: {sanitize(r['trigger'])} → Do: {sanitize(r['action'])}{tool_label}{id_label}"
            if r.get("reasoning"):
                formatted += f" | Why: {sanitize(r['reasoning'])}"
            if r.get("application"):
                formatted += f" | How: {sanitize(r['application'])}"
                
            if tool_priority in ("critical", "high"):
                critical_items.append(formatted)
            else:
                normal_items.append(formatted)
        if critical_items:
            stable_sections.append(BudgetedSection("Tool Safety Rules (must follow)", critical_items, priority=2))
        if normal_items:
            untrusted_sections.append(BudgetedSection("Learned Rules (from past interactions)", normal_items, priority=5))

    is_cold = not stable_sections and not untrusted_sections

    # Cold start: guide the agent to actively learn about the user
    if is_cold:
        return _COLD_START_CONTEXT, None

    truncation_message = (
        "\n... (Some lower-priority memory items were truncated to preserve prompt stability. "
        "Use memory_recall tool to search for more.)"
    )
    escaped_untrusted = [
        BudgetedSection(sec.title, [_escape_xml_item(i) for i in sec.items], priority=sec.priority)
        for sec in untrusted_sections
    ]

    stable_body, untrusted_body = _partition_budget_sections(
        stable_sections,
        escaped_untrusted,
        max_tokens=2500,
        truncation_message=truncation_message,
    )

    stable_formatted = None
    if stable_body:
        base_header = "# User Context (stable)\n\n"
        stable_formatted = f"""<user_memory_context>
{base_header}{stable_body}
</user_memory_context>"""

    untrusted_formatted = None
    if untrusted_body:
        wrapped_body = wrap_untrusted(untrusted_body, source="memory_context")

        untrusted_formatted = f"""{wrapped_body}

## Citation Requirements
When your answer directly relies on any provided memory or rule (from either stable or learned contexts), you MUST append a citation tag at the end of the relevant sentence or paragraph.
Format: <cite:MEMORY_ID>
Example: "Based on your preference for concise answers <cite:mem-123>, here is the script."

## Memory Search
Use memory_recall for durable user facts, preferences, profile data, learned rules, project stack, and coding conventions.
Use conversation_search for prior chat evidence, earlier decisions, branch/fork context, or requests like "last time", "previously", and "continue that discussion".
Memories and recalled conversations are point-in-time records. If recalled info conflicts with current observations, trust what you see now."""

    return stable_formatted, untrusted_formatted


_COLD_START_CONTEXT = """<user_memory_context>
# New User — Discovery Mode

No memories yet. Actively learn about this user during the conversation:
- Note their name, role, and tech stack when mentioned
- Observe communication style preferences (language, verbosity, formality)
- Track project context and domain expertise
- Use memory_save to persist key observations

This guidance will be replaced by real user context as memories accumulate.

## Citation Requirements
When your answer directly relies on any provided memory or rule (from either stable or learned contexts), you MUST append a citation tag at the end of the relevant sentence or paragraph.
Format: <cite:MEMORY_ID>
Example: "Based on your preference for concise answers <cite:mem-123>, here is the script."

## Memory Search
Use memory_recall for durable user facts, preferences, profile data, learned rules, project stack, and coding conventions.
Use conversation_search for prior chat evidence, earlier decisions, branch/fork context, or requests like "last time", "previously", and "continue that discussion".
Memories and recalled conversations are point-in-time records. If recalled info conflicts with current observations, trust what you see now.
</user_memory_context>"""


class MemoryContextMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Inject user memory context on first LLM call.

    Stable context is appended as ``SystemMessage`` after leading systems; learned
    context is appended as ``HumanMessage`` with ``<<<UNTRUSTED_DATA>>>`` framing
    before the user's first HumanMessage.

    Requires context key: "memory_manager" (MemoryManager with user_id bound).
    """
    name = "memory_context_middleware"

    async def awrap_model_call(
        self,
        request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
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

        stable_formatted, untrusted_formatted = _format_memory_context(memory_ctx, learned_ctx)
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
        is_cold = stable_formatted == _COLD_START_CONTEXT
        
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
