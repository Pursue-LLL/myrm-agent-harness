"""Agent memory tools: search, save, manage.

Framework-level: depends only on MemoryManager (protocol-based).
Server binds wiki and conversation providers via MemorySearchBackends.

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager)
- toolkits.memory.agent_surface.memory_search_policy::MemorySearchPolicy (POS: corpus ACL for memory_search_tool)
- toolkits.memory.agent_surface.memory_search_execution (POS: memory/wiki/sessions search execution helpers)
- toolkits.memory.agent_surface.wiki_memory_boundary (POS: wiki-memory write boundary heuristics)
- toolkits.memory.agent_surface._memory_agent_tool_descriptions (POS: LLM-visible memory tool description SSOT)

[OUTPUT]
- create_memory_tools: Create memory_search_tool, memory_save_tool, memory_manage_tool.

[POS]
Agent memory tools factory. Unified read plane via memory_search_tool(corpus); write plane unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.agent_surface._memory_agent_tool_descriptions import (
    build_memory_save_tool_description,
    build_memory_search_tool_description,
    resolve_memory_manage_tool_description,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_budget import (
    DEFAULT_RECALL_LIMIT,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    format_preference_save_ack,
    format_profile_recall_output,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    parse_time_bound as _parse_time_bound,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
    search_memory_corpus,
    search_sessions_corpus,
    search_wiki_corpus,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchBackends,
    MemorySearchCorpus,
    MemorySearchPolicy,
    resolve_search_corpora,
)
from myrm_agent_harness.toolkits.memory.agent_surface.wiki_memory_boundary import (
    looks_like_wiki_document,
    record_wiki_memory_save_rejection,
    wiki_memory_save_rejection_message,
)
from myrm_agent_harness.toolkits.memory.config import RecallMode
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType, RuleSource

logger = logging.getLogger(__name__)


CATEGORY_TO_TYPE: dict[str, MemoryType] = {
    "knowledge": MemoryType.SEMANTIC,
    "claim": MemoryType.CLAIM,
    "event": MemoryType.EPISODIC,
    "preference": MemoryType.PROFILE,
    "rule": MemoryType.PROCEDURAL,
    "instruction": MemoryType.PROCEDURAL,
    "integration": MemoryType.INTEGRATION,
}


def create_memory_tools(
    manager: MemoryManager,
    recall_mode: RecallMode = RecallMode.HYBRID,
    *,
    search_policy: MemorySearchPolicy | None = None,
    search_backends: MemorySearchBackends | None = None,
    description_locale: str | None = None,
) -> list[object]:
    """Create memory tools for the user bound to the manager.

    Args:
        manager: MemoryManager instance (user_id is set at construction).
            If ``manager.approval_required`` is True, memory_save will
            route through the approval queue automatically.
        recall_mode: Controls tool visibility.
            HYBRID (default): all tools exposed.
            CONTEXT: no tools (context injection only, for API/headless).
            TOOLS: all tools exposed (no context injection handled here).
        search_policy: Runtime ACL for memory_search_tool corpus selection.
        search_backends: Optional wiki/sessions providers bound by server.
        description_locale: BCP-47 locale for LLM-facing tool descriptions (default English).
    """
    if recall_mode == RecallMode.CONTEXT:
        return []

    policy = search_policy or MemorySearchPolicy()
    backends = search_backends or MemorySearchBackends()
    tools: list[object] = []

    _search_description = build_memory_search_tool_description(
        policy, locale=description_locale
    )
    _save_description = build_memory_save_tool_description(
        policy,
        approval_required=manager.approval_required,
        locale=description_locale,
    )
    _manage_description = resolve_memory_manage_tool_description(description_locale)

    class MemorySaveInput(BaseModel):
        content: str = Field(
            description="Declarative fact text; concise and standalone."
        )
        category: Literal["knowledge", "event", "preference", "rule", "instruction"] = (
            Field(
                default="knowledge",
                description=(
                    "knowledge | event | preference | rule | instruction — see tool description for category guide"
                ),
            )
        )
        importance: float = Field(
            default=0.5,
            description="0–1 score; primarily for knowledge (see description guide).",
        )
        tags: list[str] | str | None = Field(
            default=None,
            description='Filter labels; knowledge category only (e.g. ["python", "auth"]).',
        )
        write_target: Literal["bound", "shared"] = Field(
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

    class MemoryManageInput(BaseModel):
        action: Literal["update", "delete", "correct", "rate"] = Field(
            description=(
                "update: wording/importance only; correct: wrong knowledge fact; delete; rate — see tool description"
            ),
        )
        memory_id: str = Field(description="Memory ID from memory_search_tool results.")
        category: Literal["knowledge", "event", "preference", "rule"] = Field(
            description=(
                "knowledge | event | preference | rule — instruction saves use category=rule (always trigger)"
            ),
        )
        new_content: str | None = Field(
            default=None,
            description=(
                "Required for update (wording/importance) and correct (wrong fact, knowledge only)."
            ),
        )
        new_importance: float | None = Field(
            default=None,
            description="Optional new importance for update.",
        )
        rating_score: int | None = Field(
            default=None,
            description="Required for rate; integer 1-5.",
        )

    @tool("memory_search_tool", description=_search_description)
    async def memory_search(
        query: str,
        corpus: MemorySearchCorpus = "memory",
        categories: list[str] | str | None = None,
        limit: int | str | None = DEFAULT_RECALL_LIMIT,
        profile_key: str | None = None,
        since: str | None = None,
        until: str | None = None,
        expand_conversation_id: str | None = None,
        expand_message_id: str | None = None,
    ) -> str:
        """Search long-term memory."""
        if profile_key:
            if corpus not in ("memory", "all"):
                return "profile_key lookup is only supported for corpus=memory."
            if not manager.has_relational:
                return "Profile memory is not enabled."
            value = await manager.get_profile_attribute(profile_key)
            if value is None:
                return f"No profile attribute '{profile_key}' found."
            return format_profile_recall_output(profile_key, value)

        corpora, reject_reason = resolve_search_corpora(corpus, policy)
        if reject_reason:
            return reject_reason
        if not corpora:
            return "No search corpora available."

        parsed_cats = _parse_string_list(categories)
        category_names = [c for c in parsed_cats if c in CATEGORY_TO_TYPE] or None
        parsed_since = _parse_time_bound(since)
        parsed_until = _parse_time_bound(until)
        recall_limit = normalize_recall_limit(limit)
        sections: list[str] = []

        retrieval_timeout = getattr(
            getattr(manager, "_config", None), "retrieval", None
        )
        timeout_seconds = getattr(retrieval_timeout, "timeout_seconds", 5.0)

        for target in corpora:
            if target == "memory":
                memory_text = await search_memory_corpus(
                    manager,
                    query=query,
                    category_to_type=CATEGORY_TO_TYPE,
                    categories=category_names,
                    limit=recall_limit,
                    since=since,
                    until=until,
                )
                sections.append(f"## Memory\n{memory_text}")
            elif target == "wiki":
                wiki_text = await search_wiki_corpus(
                    backends,
                    query,
                    timeout_seconds=timeout_seconds,
                )
                sections.append(f"## Wiki\n{wiki_text}")
            elif target == "sessions":
                if expand_message_id and not expand_conversation_id:
                    return "expand_message_id requires expand_conversation_id when corpus=sessions."
                session_text = await search_sessions_corpus(
                    backends,
                    query=query,
                    limit=recall_limit,
                    since=parsed_since,
                    until=parsed_until,
                    expand_conversation_id=expand_conversation_id,
                    expand_message_id=expand_message_id,
                    timeout_seconds=timeout_seconds,
                )
                sections.append(f"## Sessions\n{session_text}")

        if len(sections) == 1 and corpus != "all":
            single = sections[0]
            _prefix_map: dict[MemorySearchCorpus, str] = {
                "memory": "## Memory\n",
                "wiki": "## Wiki\n",
                "sessions": "## Sessions\n",
            }
            prefix = _prefix_map.get(corpus, "")
            if prefix and single.startswith(prefix):
                return single[len(prefix) :]
        return "\n\n".join(sections)

    tools.append(memory_search)

    @tool(
        "memory_save_tool", description=_save_description, args_schema=MemorySaveInput
    )
    async def memory_save(
        content: str,
        category: Literal[
            "knowledge", "event", "preference", "rule", "instruction"
        ] = "knowledge",
        importance: float = 0.5,
        tags: list[str] | str | None = None,
        write_target: Literal["bound", "shared"] = "bound",
        preference_key: str | None = None,
        rule_trigger: str | None = None,
        rule_priority: int = 0,
        rule_keywords: list[str] | str | None = None,
    ) -> str:
        """Persist a new memory entry for the user."""
        parsed_tags = _parse_string_list(tags)
        parsed_kw = _parse_string_list(rule_keywords)
        session = manager.active_session
        pending = manager.approval_required

        if (
            policy.allow_wiki
            and category in ("knowledge", "event")
            and looks_like_wiki_document(content)
        ):
            record_wiki_memory_save_rejection()
            return wiki_memory_save_rejection_message()

        effective_write_target = write_target
        if not policy.allow_shared_write and write_target == "shared":
            effective_write_target = "bound"

        try:
            if category == "knowledge":
                if not manager.has_vector:
                    return "Knowledge memory is not enabled."
                if session and not pending and effective_write_target == "bound":
                    mem = session.add_knowledge(
                        content, importance=importance, tags=parsed_tags
                    )
                    if mem is None:
                        return (
                            "Knowledge already exists in session (duplicate detected)"
                        )
                    return f"Knowledge buffered (ID: {mem.id})"
                mem = await manager.add_knowledge(
                    content,
                    importance=importance,
                    tags=parsed_tags,
                    write_target=effective_write_target,
                )
                return f"Knowledge {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            if category == "event":
                if not manager.has_vector:
                    return "Event memory is not enabled."
                if session and not pending and effective_write_target == "bound":
                    mem = session.add_event(content, event_type="agent_observation")
                    if mem is None:
                        return "Event already exists in session (duplicate detected)"
                    return f"Event buffered (ID: {mem.id})"
                mem = await manager.add_event(
                    content, event_type="agent_observation", write_target=effective_write_target
                )
                return f"Event {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            if category == "preference":
                if not manager.has_relational:
                    return "Profile memory is not enabled."
                if not preference_key:
                    return "Preference requires 'preference_key'."
                if session and not pending:
                    await session.set_profile(preference_key, content)
                else:
                    result = await manager.set_profile_attribute(
                        preference_key, content
                    )
                    if result is not None:
                        return f"Preference '{preference_key}' submitted for approval"
                return format_preference_save_ack(preference_key, content)

            if category == "rule":
                if not manager.has_relational:
                    return "Procedural memory is not enabled."
                if not rule_trigger:
                    return "Rule requires 'rule_trigger'."
                if session and not pending:
                    mem = session.add_rule(
                        rule_trigger,
                        content,
                        priority=rule_priority,
                        trigger_keywords=parsed_kw,
                    )
                    if mem is None:
                        return "Rule already exists in session (duplicate detected)"
                    return f"Rule buffered (ID: {mem.id})"
                mem = await manager.add_rule(
                    rule_trigger,
                    content,
                    priority=rule_priority,
                    trigger_keywords=parsed_kw,
                )
                return f"Rule {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            if category == "instruction":
                if not manager.has_relational:
                    return "Procedural memory is not enabled."
                if session and not pending:
                    mem = session.add_rule(
                        "always",
                        content,
                        priority=max(rule_priority, 10),
                        source=RuleSource.AGENT_SELF,
                    )
                    if mem is None:
                        return (
                            "Instruction already exists in session (duplicate detected)"
                        )
                    return f"Instruction buffered (ID: {mem.id})"
                mem = await manager.add_rule(
                    "always",
                    content,
                    priority=max(rule_priority, 10),
                    source=RuleSource.AGENT_SELF,
                )
                return f"Instruction {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            return f"Unknown category: {category}"
        except Exception as e:
            logger.warning("memory_save failed: %s", e)
            return "Failed to store memory"

    tools.append(memory_save)

    @tool(
        "memory_manage_tool",
        description=_manage_description,
        args_schema=MemoryManageInput,
    )
    async def memory_manage(
        action: Literal["update", "delete", "correct", "rate"],
        memory_id: str,
        category: Literal["knowledge", "event", "preference", "rule"],
        new_content: str | None = None,
        new_importance: float | None = None,
        rating_score: int | None = None,
    ) -> str:
        """Update, delete, correct, or rate an existing memory entry."""
        try:
            mem_type = CATEGORY_TO_TYPE.get(category)
            if mem_type is None:
                return f"Unknown category: {category}"

            if action == "rate":
                if rating_score is None:
                    return "Rate requires 'rating_score' (1-5)."
                if mem_type not in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
                    return "Rate action is only supported for knowledge/event memories."
                if not manager.has_vector:
                    return f"{category} memory is not enabled."
                ok = await manager.rate_memory(memory_id, rating_score)
                if ok:
                    return f"Memory rated (ID: {memory_id}, score: {rating_score})"
                return f"Memory not found (ID: {memory_id})"

            if action == "delete":
                if mem_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
                    if not manager.has_vector:
                        return f"{category} memory is not enabled."
                    coll = (
                        manager.config.semantic_collection
                        if mem_type == MemoryType.SEMANTIC
                        else manager.config.episodic_collection
                    )
                    n = await manager.delete_memory(
                        coll, [memory_id], allow_pinned=False
                    )
                    if n > 0:
                        return f"Memory deleted (ID: {memory_id})"
                    return (
                        f"Cannot delete memory (ID: {memory_id}): "
                        "it may be pinned or not found. Pinned memories cannot be deleted by the agent."
                    )

                if mem_type == MemoryType.PROFILE:
                    return "Profile attributes cannot be deleted via memory_manage."

                if mem_type == MemoryType.PROCEDURAL:
                    if not manager.has_relational:
                        return "Procedural memory is not enabled."
                    ok = await manager.delete_rule(memory_id, allow_pinned=False)
                    if ok:
                        return f"Rule deleted (ID: {memory_id})"
                    return (
                        f"Cannot delete rule (ID: {memory_id}): "
                        "it may be pinned or not found. Pinned rules cannot be deleted by the agent."
                    )

            elif action == "update":
                if not new_content:
                    return "Update requires 'new_content'."
                updated = await manager.update_memory(
                    memory_id, content=new_content, importance=new_importance
                )
                return f"Memory updated (ID: {updated.id})"

            elif action == "correct":
                if not new_content:
                    return "Correct requires 'new_content' with the corrected fact."
                if mem_type != MemoryType.SEMANTIC:
                    return "Correct action is only supported for knowledge memories."
                if not manager.has_vector:
                    return "Knowledge memory is not enabled."
                correction = await manager.correct_memory(memory_id, new_content)
                return f"Memory corrected (new ID: {correction.id}). Prior entry {memory_id} kept in history."

            return f"Unknown action: {action}"
        except Exception as e:
            logger.warning("memory_manage failed: %s", e)
            return "Failed to manage memory"

    tools.append(memory_manage)
    return tools


def _parse_string_list(val: list[str] | str | None) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [t.strip() for t in val.split(",") if t.strip()]
