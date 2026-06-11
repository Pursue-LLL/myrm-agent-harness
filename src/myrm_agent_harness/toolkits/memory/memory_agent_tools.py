"""Agent memory tools: recall, save, manage.

Framework-level: depends only on MemoryManager (protocol-based).
All approval logic is handled transparently by MemoryManager.

[INPUT]
- agent.streaming.types::AgentEventType (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- memory_age_label: Human-readable age label for a memory timestamp.
- create_memory_tools: Create memory tools for the user bound to the manager.

[POS]
Agent memory tools: recall, save, manage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from langchain_core.tools import tool

from myrm_agent_harness.toolkits.memory.config import RecallMode
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.memory_citations import cited_memory_ref, emit_cited_memory_ids
from myrm_agent_harness.toolkits.memory.memory_recall_budget import (
    DEFAULT_RECALL_LIMIT,
    MAX_RECALL_OUTPUT_CHARS,
    budget_recall_line,
    line_cost,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    channel_label as _channel_label,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    is_stale as _is_stale,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    memory_age_label,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    parse_time_bound as _parse_time_bound,
)
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    MemorySearchResult,
    MemoryType,
    RuleSource,
    SemanticMemory,
)

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

_DRIFT_DEFENSE_FOOTER = (
    "\n---\n"
    "Note: Before acting on recalled memories:\n"
    "- If a memory references files/functions → verify they still exist\n"
    "- If a memory states configs/versions → check current project state\n"
    "- If a memory conflicts with current observations → trust current observation\n"
    "To fix outdated memories: use memory_manage(action='correct') or memory_manage(action='delete')"
)

_CODE_PATH_PATTERN = re.compile(
    r"(\/[a-zA-Z0-9_\-\.]+)+\/?|[a-zA-Z0-9_\-\.]+\.(py|ts|tsx|js|jsx|json|yaml|yml|md|rs|go|java|c|cpp|h|hpp)"
)


def create_memory_tools(manager: MemoryManager, recall_mode: RecallMode = RecallMode.HYBRID) -> list[object]:
    """Create memory tools for the user bound to the manager.

    Args:
        manager: MemoryManager instance (user_id is set at construction).
            If ``manager.approval_required`` is True, memory_save will
            route through the approval queue automatically.
        recall_mode: Controls tool visibility.
            HYBRID (default): all tools exposed.
            CONTEXT: no tools (context injection only, for API/headless).
            TOOLS: all tools exposed (no context injection handled here).
    """
    if recall_mode == RecallMode.CONTEXT:
        return []

    tools: list[object] = []

    @tool("memory_recall_tool")
    async def memory_recall(
        query: str,
        categories: list[str] | str | None = None,
        limit: int | str | None = DEFAULT_RECALL_LIMIT,
        profile_key: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        """Search user memories or retrieve a specific profile attribute.

        Use this tool when the user's question relates to their personal context,
        preferences, past discussions, or ongoing projects.

        **When to call immediately**:
        - User asks "my preferences", "what I like", "my settings"
        - User references "we discussed", "last time", "previously", "you mentioned"
        - User asks "what do you know about me", "my profile"
        - User mentions "my projects", "my code", "my work"

        **Search tips**:
        - Use specific queries: "user's Python framework preference" not just "Python"
        - Filter by categories when known: knowledge (facts), claim (compiled knowledge),
          event (conversations), preference (likes/dislikes), rule (behavioral patterns)
        - Increase limit if initial results seem insufficient (try 10-15)
        - Use profile_key for instant attribute lookup (faster than semantic search)
        - Use since/until when the user mentions time: "last week", "yesterday", "recently"

        Args:
            query: Semantic search query. Be specific for better results.
            categories: Filter by: knowledge, claim, event, preference, rule.
            limit: Max results (default 5, clamped to 1-15 for context safety).
            profile_key: Quick-access a profile attribute (e.g. "name").
            since: Only return memories created after this time.
                Accepts relative shorthand (7d, 2w, 1m, 24h, 1y) or ISO 8601.
            until: Only return memories created before this time.
                Accepts relative shorthand or ISO 8601.

        Returns:
            Formatted memory results with relevance scores, or specific profile value.
        """
        if profile_key:
            if not manager.has_relational:
                return "Profile memory is not enabled."
            value = await manager.get_profile_attribute(profile_key)
            if value is None:
                return f"No profile attribute '{profile_key}' found."
            return f"{profile_key}: {value}"

        parsed_cats = _parse_string_list(categories)
        types: list[MemoryType] | None = None
        if parsed_cats:
            valid = [CATEGORY_TO_TYPE[c] for c in parsed_cats if c in CATEGORY_TO_TYPE]
            types = valid or None

        parsed_since = _parse_time_bound(since)
        parsed_until = _parse_time_bound(until)
        recall_limit = normalize_recall_limit(limit)
        results = await manager.search(
            query,
            memory_types=types,
            limit=recall_limit,
            since=parsed_since,
            until=parsed_until,
        )
        output: list[str] = []
        displayed_results: list[MemorySearchResult] = []
        max_body_chars = MAX_RECALL_OUTPUT_CHARS - (len(_DRIFT_DEFENSE_FOOTER) if results else 0)
        output_chars = 0
        truncated_by_budget = False

        session = manager.active_session
        if session and session.buffer_size > 0 and query:
            for m in session.search_buffer(query):
                budgeted = budget_recall_line(
                    prefix="[buffered] ",
                    content=m.content,
                    suffix="",
                    output_chars=output_chars,
                    max_body_chars=max_body_chars,
                )
                if budgeted.line is None:
                    truncated_by_budget = True
                    break
                output.append(budgeted.line)
                output_chars = budgeted.next_chars
                truncated_by_budget = truncated_by_budget or budgeted.truncated

        if not results and not output:
            if manager.last_retrieval_trace is not None:
                await emit_cited_memory_ids([], [], retrieval_trace=manager.last_retrieval_trace)
            return "No relevant memories found."

        for r in results:
            cat = next((k for k, v in CATEGORY_TO_TYPE.items() if v == r.memory_type), r.memory_type.value)
            mem = r.memory
            age = memory_age_label(mem.created_at)
            provenance = _channel_label(mem.scope.channel_id)
            prefix = f"{provenance}[{cat}] (id: {mem.id}, score: {r.score:.2f}, {age}) "
            suffix = ""
            if isinstance(mem, ClaimMemory):
                freshness = mem.freshness
                contradiction = mem.contradiction_status
                evidence_count = mem.evidence_count
                relation_type = str(mem.metadata.get("latest_relationship_type", "")).strip().lower()
                relation_suffix = f" relation={relation_type}" if relation_type else ""
                suffix += (
                    f" [claim_graph freshness={freshness} contradiction={contradiction} "
                    f"evidence={evidence_count}{relation_suffix}]"
                )
            if isinstance(mem, SemanticMemory) and mem.source_error:
                suffix += f" (avoid: {mem.source_error})"
            # Staleness warning only for fact/event memories, not behavioral rules
            if r.memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CLAIM) and _is_stale(
                mem.created_at
            ):
                has_code_paths = bool(_CODE_PATH_PATTERN.search(mem.content))
                # Check if Agent has Read tools (tool_capture_hook implies session context where tools are evaluated)
                # But since we can't easily introspect the entire Agent toolkit here without circular deps,
                # we'll use a dynamic fallback instruction.
                if has_code_paths:
                    suffix += "\n[CRITICAL: Outdated memory referencing potential paths. YOU MUST USE Read/Grep TOOLS TO VERIFY BEFORE CITING IF AVAILABLE, OR DO NOT BLINDLY TRUST]"
                else:
                    suffix += " (may be outdated — verify before citing)"
            budgeted = budget_recall_line(
                prefix=prefix,
                content=r.content,
                suffix=suffix,
                output_chars=output_chars,
                max_body_chars=max_body_chars,
            )
            if budgeted.line is None:
                truncated_by_budget = True
                break
            output.append(budgeted.line)
            displayed_results.append(r)
            output_chars = budgeted.next_chars
            truncated_by_budget = truncated_by_budget or budgeted.truncated

        if truncated_by_budget:
            notice = (
                "[recall_budget] Some recalled content was truncated to keep this tool result within "
                f"{MAX_RECALL_OUTPUT_CHARS} chars. Refine the query or lower limit for more detail."
            )
            if output_chars + line_cost(notice) <= max_body_chars:
                output.append(notice)

        if displayed_results:
            _ratable_types = (MemoryType.SEMANTIC, MemoryType.EPISODIC)
            cited_ids = [r.memory.id for r in displayed_results if r.memory.id and r.memory_type in _ratable_types]
            cited_refs = [
                cited_memory_ref(r.memory, r.memory_type, r.score)
                for r in displayed_results
                if r.memory.id and r.memory_type in _ratable_types
            ]
            if cited_ids:
                manager.set_last_cited_memory_ids(cited_ids)
            if cited_ids or manager.last_retrieval_trace is not None:
                await emit_cited_memory_ids(cited_ids, cited_refs, retrieval_trace=manager.last_retrieval_trace)
        elif manager.last_retrieval_trace is not None:
            await emit_cited_memory_ids([], [], retrieval_trace=manager.last_retrieval_trace)

        text = "\n".join(output)
        if displayed_results:
            text += _DRIFT_DEFENSE_FOOTER
        return text

    tools.append(memory_recall)

    @tool("memory_save_tool")
    async def memory_save(
        content: str,
        category: Literal["knowledge", "event", "preference", "rule", "instruction"] = "knowledge",
        importance: float = 0.5,
        tags: list[str] | str | None = None,
        write_target: Literal["bound", "shared"] = "bound",
        preference_key: str | None = None,
        rule_trigger: str | None = None,
        rule_priority: int = 0,
        rule_keywords: list[str] | str | None = None,
    ) -> str:
        """Store a new memory for the user. Memory persists across sessions and is injected
        into future conversations, so keep entries compact and focused on durable facts.

        **WHEN TO SAVE** (do this proactively):
        - User explicitly says "remember this", "note this", "don't forget"
        - User corrects your behavior or output style
        - User shares a stable preference, habit, or personal detail (name, role, timezone)
        - You discover something about the user's environment or project that won't change soon
        - User sets a rule: "always do X" / "never do Y"

        **WHAT NOT TO SAVE**:
        - Task progress, session outcomes, completed-work logs (use conversation_search instead)
        - Temporary state: PR numbers, commit SHAs, current file paths, WIP items
        - Information that will be stale within a week
        - Step-by-step procedures or workflows (not suitable for memory)
        - Raw data dumps, code snippets, or lengthy text

        **CONTENT QUALITY** — write as declarative facts, not instructions:
        - GOOD: "User prefers dark themes" (declarative fact)
        - BAD: "Always use dark theme" (instruction-style, gets misinterpreted as a command)
        - One fact per memory entry; include enough context to be useful standalone

        **ATTRIBUTION & TRANSIENT STATES** (CRITICAL):
        - Strictly distinguish the user from third parties (family, friends, colleagues). NEVER attribute a third party's traits, illnesses, or preferences to the user. (e.g., "User's boss prefers dark mode", NOT "User prefers dark mode").
        - DO NOT save transient emotional or psychological states (e.g., "User is feeling anxious today") unless explicitly stated as a chronic condition.

        **CATEGORY GUIDE**:
        - knowledge: stable facts about user's world (project tech stack, environment details)
        - event: significant past occurrences worth recalling (user started new project)
        - preference: user likes/dislikes (requires preference_key)
        - rule: conditional behavioral rules (requires rule_trigger)
        - instruction: global instructions that always apply (highest priority)

        **IMPORTANCE SCORING**:
        - 0.8–1.0: User explicitly asked to remember / correction of your behavior
        - 0.5–0.7: Inferred stable preference or environment fact
        - 0.2–0.4: Supplementary context, nice-to-have

        **WRITE TARGET**:
        - "bound" (default): visible only to the current agent persona
        - "shared": cross-agent knowledge (user's name, timezone) — use sparingly

        Args:
            content: Memory content text — declarative, concise, standalone.
            category: knowledge | event | preference | rule | instruction.
            importance: 0–1 importance score (see scoring guide above).
            tags: Classify this memory with descriptive labels for later filtering
                (e.g. ["python", "auth"], ["cooking", "italian"]). Knowledge/event only.
            write_target: "bound" for current agent; "shared" for cross-agent knowledge.
            preference_key: Required for preference category (e.g. "response_style").
            rule_trigger: Required for rule category (context that triggers the rule).
            rule_priority: Priority for rules (higher = stronger override).
            rule_keywords: Optional trigger keywords for rule activation.
        """
        parsed_tags = _parse_string_list(tags)
        parsed_kw = _parse_string_list(rule_keywords)
        session = manager.active_session
        pending = manager.approval_required

        try:
            if category == "knowledge":
                if not manager.has_vector:
                    return "Knowledge memory is not enabled."
                if session and not pending and write_target == "bound":
                    mem = session.add_knowledge(content, importance=importance, tags=parsed_tags)
                    if mem is None:
                        return "Knowledge already exists in session (duplicate detected)"
                    return f"Knowledge buffered (ID: {mem.id})"
                mem = await manager.add_knowledge(
                    content, importance=importance, tags=parsed_tags, write_target=write_target
                )
                return f"Knowledge {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            if category == "event":
                if not manager.has_vector:
                    return "Event memory is not enabled."
                if session and not pending and write_target == "bound":
                    mem = session.add_event(content, event_type="agent_observation")
                    if mem is None:
                        return "Event already exists in session (duplicate detected)"
                    return f"Event buffered (ID: {mem.id})"
                mem = await manager.add_event(content, event_type="agent_observation", write_target=write_target)
                return f"Event {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            if category == "preference":
                if not manager.has_relational:
                    return "Profile memory is not enabled."
                if not preference_key:
                    return "Preference requires 'preference_key'."
                if session and not pending:
                    await session.set_profile(preference_key, content)
                else:
                    result = await manager.set_profile_attribute(preference_key, content)
                    if result is not None:
                        return f"Preference '{preference_key}' submitted for approval"
                return f"Preference '{preference_key}' set to '{content}'"

            if category == "rule":
                if not manager.has_relational:
                    return "Procedural memory is not enabled."
                if not rule_trigger:
                    return "Rule requires 'rule_trigger'."
                if session and not pending:
                    mem = session.add_rule(rule_trigger, content, priority=rule_priority, trigger_keywords=parsed_kw)
                    if mem is None:
                        return "Rule already exists in session (duplicate detected)"
                    return f"Rule buffered (ID: {mem.id})"
                mem = await manager.add_rule(rule_trigger, content, priority=rule_priority, trigger_keywords=parsed_kw)
                return f"Rule {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            if category == "instruction":
                if not manager.has_relational:
                    return "Procedural memory is not enabled."
                if session and not pending:
                    mem = session.add_rule(
                        "always", content, priority=max(rule_priority, 10), source=RuleSource.AGENT_SELF
                    )
                    if mem is None:
                        return "Instruction already exists in session (duplicate detected)"
                    return f"Instruction buffered (ID: {mem.id})"
                mem = await manager.add_rule(
                    "always", content, priority=max(rule_priority, 10), source=RuleSource.AGENT_SELF
                )
                return f"Instruction {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            return f"Unknown category: {category}"
        except Exception as e:
            logger.warning(f"memory_save failed: {e}")
            return f"Failed to store memory: {e}"

    tools.append(memory_save)

    @tool("memory_manage_tool")
    async def memory_manage(
        action: Literal["update", "delete", "correct", "rate"],
        memory_id: str,
        category: Literal["knowledge", "event", "preference", "rule"],
        new_content: str | None = None,
        new_importance: float | None = None,
        rating_score: int | None = None,
    ) -> str:
        """Update, delete, correct, or rate an existing memory.

        **WHEN TO USE**:
        - User says "forget that" / "that's wrong" / "remove that memory" → delete or correct
        - A recalled memory is outdated or inaccurate → correct (preserves history)
        - User confirms a memory is helpful → rate (reinforces retrieval ranking)
        - A memory needs minor wording fix → update

        Args:
            action: "update", "delete", "correct", or "rate".
            memory_id: Memory ID from memory_recall results.
            category: knowledge | event | preference | rule.
            new_content: Required for update/correct actions.
            new_importance: Optional new importance score.
            rating_score: Required for rate action (1-5, where 1=bad, 5=excellent).

        The "correct" action is for when a memory is factually wrong.
        It demotes the old memory (low confidence) and creates a new
        high-confidence correction memory linked to it, so future
        retrievals automatically prefer the corrected version.

        The "rate" action records user feedback on a memory. Higher-rated
        memories are ranked higher in search results and resist forgetting.
        """
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
                    n = await manager.delete_memory(coll, [memory_id], allow_pinned=False)
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
                updated = await manager.update_memory(memory_id, content=new_content, importance=new_importance)
                return f"Memory updated (ID: {updated.id})"

            elif action == "correct":
                if not new_content:
                    return "Correct requires 'new_content' with the corrected fact."
                if mem_type != MemoryType.SEMANTIC:
                    return "Correct action is only supported for knowledge memories."
                if not manager.has_vector:
                    return "Knowledge memory is not enabled."
                correction = await manager.correct_memory(memory_id, new_content)
                return f"Memory corrected: old memory {memory_id} demoted, new correction stored (ID: {correction.id})"

            return f"Unknown action: {action}"
        except Exception as e:
            logger.warning(f"memory_manage failed: {e}")
            return f"Failed to manage memory: {e}"

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
