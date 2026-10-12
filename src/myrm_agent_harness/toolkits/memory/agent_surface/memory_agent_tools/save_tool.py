"""memory_save_tool: persist knowledge / event / preference / rule / instruction memories.

[INPUT]
- toolkits.memory.agent_surface.memory_agent_tools.common::parse_string_list (POS: Stateless helpers for memory_search/save/manage tool arguments)
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager; routes writes through the approval queue when approval_required)
- toolkits.memory.session::MemorySession (POS: per-conversation write buffer flushed at session end)
- toolkits.memory._internal.scope::MemoryWriteTarget (POS: bound / shared write target)
- toolkits.memory.types::RuleSource (POS: rule provenance enum)
- toolkits.memory.agent_surface.memory_search_policy::MemorySearchPolicy (POS: wiki / shared-write ACL)
- toolkits.memory.agent_surface.memory_recall_formatting::format_preference_save_ack (POS: recall sanitize and save-ack SSOT)
- toolkits.memory.agent_surface.wiki_memory_boundary / transient_fact_boundary (POS: pre-write rejection heuristics)
- toolkits.memory.agent_surface.write_failure_feedback (POS: LLM-readable write failure messages)

[OUTPUT]
- MemorySaveInput: pydantic args schema of memory_save_tool
- build_memory_save_tool: bind memory_save_tool to a manager and policy

[POS]
Write plane (create) of the agent memory tools; update/delete live in manage_tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory._internal.scope import MemoryWriteTarget
from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools.common import parse_string_list
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import format_preference_save_ack
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import MemorySearchPolicy
from myrm_agent_harness.toolkits.memory.agent_surface.transient_fact_boundary import (
    looks_like_transient_business_fact,
    record_transient_fact_rejection,
    transient_fact_save_rejection_message,
)
from myrm_agent_harness.toolkits.memory.agent_surface.wiki_memory_boundary import (
    looks_like_wiki_document,
    record_wiki_memory_save_rejection,
    wiki_memory_save_rejection_message,
)
from myrm_agent_harness.toolkits.memory.agent_surface.write_failure_feedback import write_failure_feedback
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.session import MemorySession
from myrm_agent_harness.toolkits.memory.types import RuleSource


class MemorySaveInput(BaseModel):
    content: str = Field(description="Declarative fact text; concise and standalone.")
    category: Literal["knowledge", "event", "preference", "rule", "instruction"] = Field(
        default="knowledge",
        description=("knowledge | event | preference | rule | instruction — see tool description for category guide"),
    )
    importance: float = Field(
        default=0.5,
        description="0–1 score; primarily for knowledge (see description guide).",
    )
    tags: list[str] | str | None = Field(
        default=None,
        description='Filter labels; knowledge category only (e.g. ["python", "auth"]).',
    )
    write_target: MemoryWriteTarget = Field(
        default="bound",
        description="bound (default) or shared cross-agent facts — use shared sparingly.",
    )
    preference_key: str | None = Field(
        default=None,
        description='Required when category=preference (e.g. "response_style").',
    )
    rule_trigger: str | None = Field(
        default=None,
        description="Required when category=rule; do not use for instruction.",
    )
    rule_priority: int = Field(
        default=0,
        description="Rule override strength when category=rule; higher wins.",
    )
    rule_keywords: list[str] | str | None = Field(
        default=None,
        description="Optional keywords that activate a rule.",
    )


@dataclass(frozen=True, slots=True)
class _SaveContext:
    """One save request: the manager, its active buffer and the resolved write mode."""

    manager: MemoryManager
    session: MemorySession | None
    pending: bool
    content: str
    write_target: MemoryWriteTarget

    @property
    def outcome(self) -> str:
        return "submitted for approval" if self.pending else "stored"

    @property
    def buffer(self) -> MemorySession | None:
        """Session buffer for writes that need no approval; ``None`` routes to the manager."""
        return None if self.pending else self.session

    @property
    def bound_buffer(self) -> MemorySession | None:
        """Session buffer for vector writes, which are buffered only when agent-bound."""
        return self.buffer if self.write_target == "bound" else None


async def _save_knowledge(ctx: _SaveContext, *, importance: float, tags: list[str]) -> str:
    if not ctx.manager.has_vector:
        return "Knowledge memory is not enabled."
    if (buffer := ctx.bound_buffer) is not None:
        buffered = buffer.add_knowledge(ctx.content, importance=importance, tags=tags)
        if buffered is None:
            return "Knowledge already exists in session (duplicate detected)"
        return f"Knowledge buffered (ID: {buffered.id})"
    stored = await ctx.manager.add_knowledge(
        ctx.content,
        importance=importance,
        tags=tags,
        write_target=ctx.write_target,
    )
    return f"Knowledge {ctx.outcome} (ID: {stored.id})"


async def _save_event(ctx: _SaveContext) -> str:
    if not ctx.manager.has_vector:
        return "Event memory is not enabled."
    if (buffer := ctx.bound_buffer) is not None:
        buffered = buffer.add_event(ctx.content, event_type="agent_observation")
        if buffered is None:
            return "Event already exists in session (duplicate detected)"
        return f"Event buffered (ID: {buffered.id})"
    stored = await ctx.manager.add_event(
        ctx.content,
        event_type="agent_observation",
        write_target=ctx.write_target,
    )
    return f"Event {ctx.outcome} (ID: {stored.id})"


async def _save_preference(ctx: _SaveContext, *, preference_key: str | None) -> str:
    if not ctx.manager.has_relational:
        return "Profile memory is not enabled."
    if not preference_key:
        return "Preference requires 'preference_key'."
    if (buffer := ctx.buffer) is not None:
        await buffer.set_profile(preference_key, ctx.content)
    else:
        result = await ctx.manager.set_profile_attribute(preference_key, ctx.content)
        if result is not None:
            return f"Preference '{preference_key}' submitted for approval"
    return format_preference_save_ack(preference_key, ctx.content)


async def _save_rule(
    ctx: _SaveContext,
    *,
    trigger: str | None,
    priority: int,
    keywords: list[str],
) -> str:
    if not ctx.manager.has_relational:
        return "Procedural memory is not enabled."
    if not trigger:
        return "Rule requires 'rule_trigger'."
    if (buffer := ctx.buffer) is not None:
        buffered = buffer.add_rule(trigger, ctx.content, priority=priority, trigger_keywords=keywords)
        if buffered is None:
            return "Rule already exists in session (duplicate detected)"
        return f"Rule buffered (ID: {buffered.id})"
    stored = await ctx.manager.add_rule(trigger, ctx.content, priority=priority, trigger_keywords=keywords)
    return f"Rule {ctx.outcome} (ID: {stored.id})"


async def _save_instruction(ctx: _SaveContext, *, priority: int) -> str:
    if not ctx.manager.has_relational:
        return "Procedural memory is not enabled."
    instruction_priority = max(priority, 10)
    if (buffer := ctx.buffer) is not None:
        buffered = buffer.add_rule(
            "always",
            ctx.content,
            priority=instruction_priority,
            source=RuleSource.AGENT_SELF,
        )
        if buffered is None:
            return "Instruction already exists in session (duplicate detected)"
        return f"Instruction buffered (ID: {buffered.id})"
    stored = await ctx.manager.add_rule(
        "always",
        ctx.content,
        priority=instruction_priority,
        source=RuleSource.AGENT_SELF,
    )
    return f"Instruction {ctx.outcome} (ID: {stored.id})"


def build_memory_save_tool(
    manager: MemoryManager,
    policy: MemorySearchPolicy,
    *,
    description: str,
) -> BaseTool:
    """Create memory_save_tool bound to ``manager`` under the given write policy."""

    @tool("memory_save_tool", description=description, args_schema=MemorySaveInput)
    async def memory_save(
        content: str,
        category: Literal["knowledge", "event", "preference", "rule", "instruction"] = "knowledge",
        importance: float = 0.5,
        tags: list[str] | str | None = None,
        write_target: MemoryWriteTarget = "bound",
        preference_key: str | None = None,
        rule_trigger: str | None = None,
        rule_priority: int = 0,
        rule_keywords: list[str] | str | None = None,
    ) -> str:
        """Persist a new memory entry for the user."""
        parsed_tags = parse_string_list(tags)
        parsed_keywords = parse_string_list(rule_keywords)

        if policy.allow_wiki and category in ("knowledge", "event") and looks_like_wiki_document(content):
            record_wiki_memory_save_rejection()
            return wiki_memory_save_rejection_message()

        if category in ("knowledge", "event") and looks_like_transient_business_fact(content):
            record_transient_fact_rejection()
            return transient_fact_save_rejection_message()

        effective_write_target: MemoryWriteTarget = write_target
        if not policy.allow_shared_write and write_target == "shared":
            effective_write_target = "bound"

        ctx = _SaveContext(
            manager=manager,
            session=manager.active_session,
            pending=manager.approval_required,
            content=content,
            write_target=effective_write_target,
        )

        try:
            if category == "knowledge":
                return await _save_knowledge(ctx, importance=importance, tags=parsed_tags)
            if category == "event":
                return await _save_event(ctx)
            if category == "preference":
                return await _save_preference(ctx, preference_key=preference_key)
            if category == "rule":
                return await _save_rule(ctx, trigger=rule_trigger, priority=rule_priority, keywords=parsed_keywords)
            if category == "instruction":
                return await _save_instruction(ctx, priority=rule_priority)
            return f"Unknown category: {category}"
        except Exception as e:
            return write_failure_feedback("memory_save", e, fallback="Failed to store memory")

    return memory_save
