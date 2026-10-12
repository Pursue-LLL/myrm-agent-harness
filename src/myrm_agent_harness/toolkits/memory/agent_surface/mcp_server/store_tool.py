"""memory_store MCP tool: persist knowledge / event / preference / rule / instruction memories.

[INPUT]
- toolkits.memory.agent_surface.wiki_memory_boundary (POS: wiki-memory write boundary heuristics)
- toolkits.memory.agent_surface.write_failure_feedback (POS: LLM-readable write failure messages)
- toolkits.memory.agent_surface.mcp_server.request_context (POS: per-request wiki boundary flag)
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager; routes writes through the approval queue when approval_required)

[OUTPUT]
- register_store_tool: register memory_store on an MCPServer

[POS]
Write plane (create) of the MCP adapter; external agents write straight to the manager (no session buffer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from mcp.server.mcpserver import MCPServer

from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.common import ManagerResolver, parse_string_list
from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.request_context import (
    get_request_wiki_boundary_enabled,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import format_preference_save_ack
from myrm_agent_harness.toolkits.memory.agent_surface.wiki_memory_boundary import (
    looks_like_wiki_document,
    record_wiki_memory_save_rejection,
    wiki_memory_save_rejection_message,
)
from myrm_agent_harness.toolkits.memory.agent_surface.write_failure_feedback import write_failure_feedback
from myrm_agent_harness.toolkits.memory.types import RuleSource

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

type WriteTarget = Literal["bound", "shared"]

_VALID_CATEGORIES = ("knowledge", "event", "preference", "rule", "instruction")


def _parse_write_target(value: str) -> WriteTarget | None:
    if value == "bound":
        return "bound"
    if value == "shared":
        return "shared"
    return None


def _outcome(pending: bool) -> str:
    return "submitted for approval" if pending else "stored"


async def _store_knowledge(
    mgr: MemoryManager,
    content: str,
    *,
    importance: float,
    tags: list[str],
    write_target: WriteTarget,
    pending: bool,
) -> str:
    if not mgr.has_vector:
        return "Knowledge memory is not enabled."
    mem = await mgr.add_knowledge(content, importance=importance, tags=tags, write_target=write_target)
    return f"Knowledge {_outcome(pending)} (ID: {mem.id})"


async def _store_event(mgr: MemoryManager, content: str, *, write_target: WriteTarget, pending: bool) -> str:
    if not mgr.has_vector:
        return "Event memory is not enabled."
    mem = await mgr.add_event(content, event_type="agent_observation", write_target=write_target)
    return f"Event {_outcome(pending)} (ID: {mem.id})"


async def _store_preference(mgr: MemoryManager, content: str, *, preference_key: str | None) -> str:
    if not mgr.has_relational:
        return "Profile memory is not enabled."
    if not preference_key:
        return "Preference requires 'preference_key'."
    result = await mgr.set_profile_attribute(preference_key, content)
    if result is not None:
        return f"Preference '{preference_key}' submitted for approval"
    return format_preference_save_ack(preference_key, content)


async def _store_rule(
    mgr: MemoryManager,
    content: str,
    *,
    trigger: str | None,
    priority: int,
    keywords: list[str],
    pending: bool,
) -> str:
    if not mgr.has_relational:
        return "Procedural memory is not enabled."
    if not trigger:
        return "Rule requires 'rule_trigger'."
    mem = await mgr.add_rule(trigger, content, priority=priority, trigger_keywords=keywords)
    return f"Rule {_outcome(pending)} (ID: {mem.id})"


async def _store_instruction(mgr: MemoryManager, content: str, *, priority: int, pending: bool) -> str:
    if not mgr.has_relational:
        return "Procedural memory is not enabled."
    mem = await mgr.add_rule("always", content, priority=max(priority, 10), source=RuleSource.AGENT_SELF)
    return f"Instruction {_outcome(pending)} (ID: {mem.id})"


def register_store_tool(mcp: MCPServer, resolve: ManagerResolver, *, description: str) -> None:
    """Register memory_store on ``mcp``; ``resolve`` supplies the request's MemoryManager."""

    @mcp.tool(name="memory_store", description=description)
    async def memory_store(
        content: str,
        category: str = "knowledge",
        importance: float = 0.5,
        tags: str | list[str] | None = None,
        write_target: str = "bound",
        preference_key: str | None = None,
        rule_trigger: str | None = None,
        rule_priority: int = 0,
        rule_keywords: str | list[str] | None = None,
    ) -> str:
        """Store a memory.

        Args:
            content: The memory content to store.
            category: knowledge | event | preference | rule | instruction.
            importance: 0.0-1.0 importance score (default 0.5).
            tags: Tags (knowledge/event only). Accepts a comma-separated
                string, a JSON array, or a raw list.
            write_target: "bound" (agent scope) or "shared" (broadest namespace).
            preference_key: Required for preference category (e.g. "language", "framework").
            rule_trigger: Required for rule category — describes when the rule applies.
            rule_priority: Priority for rules (higher = stronger, default 0).
            rule_keywords: Trigger keywords for rules. Accepts a comma-separated
                string, a JSON array, or a raw list.
        """
        if not content or not content.strip():
            return "Error: content cannot be empty."

        if category not in _VALID_CATEGORIES:
            return f"Error: invalid category '{category}'. Valid: {', '.join(_VALID_CATEGORIES)}"
        target = _parse_write_target(write_target)
        if target is None:
            return "Error: write_target must be 'bound' or 'shared'."

        mgr = resolve()
        parsed_tags = parse_string_list(tags)
        parsed_keywords = parse_string_list(rule_keywords)
        pending = mgr.approval_required

        if (
            get_request_wiki_boundary_enabled()
            and category in ("knowledge", "event")
            and looks_like_wiki_document(content)
        ):
            record_wiki_memory_save_rejection()
            return wiki_memory_save_rejection_message(include_tool_hint=False)

        try:
            if category == "knowledge":
                return await _store_knowledge(
                    mgr, content, importance=importance, tags=parsed_tags, write_target=target, pending=pending
                )
            if category == "event":
                return await _store_event(mgr, content, write_target=target, pending=pending)
            if category == "preference":
                return await _store_preference(mgr, content, preference_key=preference_key)
            if category == "rule":
                return await _store_rule(
                    mgr,
                    content,
                    trigger=rule_trigger,
                    priority=rule_priority,
                    keywords=parsed_keywords,
                    pending=pending,
                )
            return await _store_instruction(mgr, content, priority=rule_priority, pending=pending)
        except Exception as e:
            return write_failure_feedback("MCP memory_store", e, fallback="Failed to store memory")
