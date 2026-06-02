"""Memory MCP Server Adapter.

Wraps MemoryManager as an MCP server exposing memory tools
(recall, store, manage) to external agents (Claude Code, Cursor, etc.)
via the Model Context Protocol.

Tools are 1:1 feature-equivalent with the internal agent tools in
``memory_agent_tools.py``, so external agents have the same capabilities
as our built-in agent — including category filtering, time bounds,
profile attribute lookup, full CRUD management, and drift defense.

[INPUT]
- myrm_agent_harness.toolkits.memory.manager::MemoryManager (POS: Unified memory manager)
- myrm_agent_harness.toolkits.memory.types::MemoryType, SemanticMemory (POS: Memory type system)
- myrm_agent_harness.toolkits.memory.memory_recall_formatting (POS: Shared formatting helpers)
- myrm_agent_harness.toolkits.memory.memory_recall_budget (POS: Output budget guardrails)

[OUTPUT]
- MemoryMCPServer: MCP server adapter exposing memory tools
- create_memory_mcp_server: Factory function

[POS]
MCP server adapter that lets external AI agents (Claude Code, Cursor, Codex)
access the memory system via standard MCP protocol. Feature-equivalent with
the internal agent tools: recall (with categories/time/profile), store (with
5 categories), and manage (update/delete/correct/rate).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from myrm_agent_harness.toolkits.memory.memory_recall_budget import (
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
    MemoryType,
    RuleSource,
    SemanticMemory,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_CATEGORY_TO_TYPE: dict[str, MemoryType] = {
    "knowledge": MemoryType.SEMANTIC,
    "claim": MemoryType.CLAIM,
    "event": MemoryType.EPISODIC,
    "preference": MemoryType.PROFILE,
    "rule": MemoryType.PROCEDURAL,
    "instruction": MemoryType.PROCEDURAL,
}

_DRIFT_DEFENSE_FOOTER = (
    "\n---\n"
    "Note: Before acting on recalled memories:\n"
    "- If a memory references files/functions → verify they still exist\n"
    "- If a memory states configs/versions → check current project state\n"
    "- If a memory conflicts with current observations → trust current observation\n"
    "To fix outdated memories: use memory_manage(action='correct') or memory_manage(action='delete')"
)


def _parse_string_list(val: list[str] | str | None) -> list[str]:
    """Parse a value that may be a list, JSON string, or comma-separated string."""
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
    return [part.strip() for part in val.split(",") if part.strip()]


class MemoryMCPServer:
    """MCP server adapter exposing MemoryManager as MCP tools.

    Provides memory_recall, memory_store, and memory_manage tools that
    external agents can invoke via MCP protocol. Feature-equivalent with
    the internal agent tools defined in ``memory_agent_tools.py``.

    Usage:
        manager = MemoryManager(...)
        mcp_server = MemoryMCPServer(manager)
        app = mcp_server.get_streamable_http_app()  # Mount on FastAPI
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        server_name: str = "myrm-memory",
    ) -> None:
        self._manager = memory_manager
        self._mcp = FastMCP(
            server_name,
            instructions=(
                "Memory service for storing, recalling, and managing user knowledge, "
                "preferences, and project context. Use memory_recall before making "
                "assumptions. Use memory_store to save important facts. Use "
                "memory_manage to correct, rate, update, or delete memories."
            ),
        )
        self._register_tools()

    # ── Tool Registration ────────────────────────────────────────────

    def _register_tools(self) -> None:
        """Register memory tools on the MCP server."""
        self._register_recall()
        self._register_store()
        self._register_manage()

    def _register_recall(self) -> None:
        mgr = self._manager

        @self._mcp.tool(
            name="memory_recall",
            description=(
                "Search user memories or retrieve a specific profile attribute. "
                "Returns memories ranked by relevance including user preferences, "
                "project knowledge, and procedural rules.\n\n"
                "Always call this before making assumptions about user preferences "
                "or project context.\n\n"
                "Tips:\n"
                "- Use specific queries for better results\n"
                "- Filter by categories: knowledge, claim, event, preference, rule\n"
                "- Use profile_key for instant attribute lookup (e.g. 'name', 'language')\n"
                "- Use since/until for time-scoped queries (e.g. '7d', '2w', '1m')"
            ),
        )
        async def memory_recall(
            query: str,
            categories: str | None = None,
            limit: int = 5,
            profile_key: str | None = None,
            since: str | None = None,
            until: str | None = None,
        ) -> str:
            """Recall memories matching a natural language query.

            Args:
                query: Semantic search query. Be specific for better results.
                categories: Comma-separated filter: knowledge, claim, event,
                    preference, rule. None = all types.
                limit: Max results (1-15, default 5).
                profile_key: Quick-access a profile attribute (e.g. "name").
                    When set, query is ignored and returns the attribute value directly.
                since: Only return memories created after this time.
                    Accepts relative shorthand (7d, 2w, 1m, 24h, 1y) or ISO 8601.
                until: Only return memories created before this time.
                    Accepts relative shorthand or ISO 8601.
            """
            if profile_key:
                if not mgr.has_relational:
                    return "Profile memory is not enabled."
                value = await mgr.get_profile_attribute(profile_key)
                if value is None:
                    return f"No profile attribute '{profile_key}' found."
                return f"{profile_key}: {value}"

            parsed_cats = _parse_string_list(categories)
            types: list[MemoryType] | None = None
            if parsed_cats:
                valid = [_CATEGORY_TO_TYPE[c] for c in parsed_cats if c in _CATEGORY_TO_TYPE]
                types = valid or None

            parsed_since = _parse_time_bound(since)
            parsed_until = _parse_time_bound(until)
            recall_limit = normalize_recall_limit(limit)

            results = await mgr.search(
                query,
                memory_types=types,
                limit=recall_limit,
                since=parsed_since,
                until=parsed_until,
            )
            if not results:
                return "No relevant memories found."

            output: list[str] = []
            max_body_chars = MAX_RECALL_OUTPUT_CHARS - len(_DRIFT_DEFENSE_FOOTER)
            output_chars = 0
            truncated_by_budget = False

            for r in results:
                cat = next((k for k, v in _CATEGORY_TO_TYPE.items() if v == r.memory_type), r.memory_type.value)
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
                if r.memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CLAIM) and _is_stale(
                    mem.created_at
                ):
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
                output_chars = budgeted.next_chars
                truncated_by_budget = truncated_by_budget or budgeted.truncated

            if truncated_by_budget:
                notice = (
                    "[recall_budget] Some recalled content was truncated to keep this tool result within "
                    f"{MAX_RECALL_OUTPUT_CHARS} chars. Refine the query or lower limit for more detail."
                )
                if output_chars + line_cost(notice) <= max_body_chars:
                    output.append(notice)

            text = "\n".join(output)
            text += _DRIFT_DEFENSE_FOOTER
            return text

    def _register_store(self) -> None:
        mgr = self._manager

        @self._mcp.tool(
            name="memory_store",
            description=(
                "Store a durable memory for the user. Persists across sessions and is "
                "injected into future conversations. Keep entries compact and factual.\n\n"
                "SAVE when: user says 'remember this', corrects behavior, shares stable "
                "preference/personal detail, or you discover a lasting environment fact.\n"
                "DO NOT save: task progress, PR numbers, commit SHAs, temporary state, "
                "step-by-step procedures, or anything stale within a week.\n"
                "Write as declarative facts ('User prefers X'), not instructions "
                "('Always do X').\n\n"
                "Categories:\n"
                "- knowledge: stable facts (tech stack, environment)\n"
                "- event: significant past occurrences\n"
                "- preference: user likes/dislikes (requires preference_key)\n"
                "- rule: conditional behavioral rules (requires rule_trigger)\n"
                "- instruction: always-active global directives\n\n"
                "Importance: 0.8-1.0 (explicit request/correction), 0.5-0.7 (inferred "
                "fact), 0.2-0.4 (supplementary). write_target: 'bound' (current agent) "
                "or 'shared' (cross-agent, use sparingly)."
            ),
        )
        async def memory_store(
            content: str,
            category: str = "knowledge",
            importance: float = 0.5,
            tags: str | None = None,
            write_target: str = "bound",
            preference_key: str | None = None,
            rule_trigger: str | None = None,
            rule_priority: int = 0,
            rule_keywords: str | None = None,
        ) -> str:
            """Store a memory.

            Args:
                content: The memory content to store.
                category: knowledge | event | preference | rule | instruction.
                importance: 0.0-1.0 importance score (default 0.5).
                tags: Comma-separated tags (knowledge/event only).
                write_target: "bound" (agent scope) or "shared" (broadest namespace).
                preference_key: Required for preference category (e.g. "language", "framework").
                rule_trigger: Required for rule category — describes when the rule applies.
                rule_priority: Priority for rules (higher = stronger, default 0).
                rule_keywords: Comma-separated trigger keywords for rules.
            """
            if not content or not content.strip():
                return "Error: content cannot be empty."

            valid_categories = ("knowledge", "event", "preference", "rule", "instruction")
            if category not in valid_categories:
                return f"Error: invalid category '{category}'. Valid: {', '.join(valid_categories)}"
            if write_target not in ("bound", "shared"):
                return "Error: write_target must be 'bound' or 'shared'."

            parsed_tags = _parse_string_list(tags)
            parsed_kw = _parse_string_list(rule_keywords)
            pending = mgr.approval_required

            try:
                if category == "knowledge":
                    if not mgr.has_vector:
                        return "Knowledge memory is not enabled."
                    mem = await mgr.add_knowledge(
                        content, importance=importance, tags=parsed_tags, write_target=write_target
                    )
                    return f"Knowledge {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

                if category == "event":
                    if not mgr.has_vector:
                        return "Event memory is not enabled."
                    mem = await mgr.add_event(
                        content, event_type="agent_observation", write_target=write_target
                    )
                    return f"Event {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

                if category == "preference":
                    if not mgr.has_relational:
                        return "Profile memory is not enabled."
                    if not preference_key:
                        return "Preference requires 'preference_key'."
                    result = await mgr.set_profile_attribute(preference_key, content)
                    if result is not None:
                        return f"Preference '{preference_key}' submitted for approval"
                    return f"Preference '{preference_key}' set to '{content}'"

                if category == "rule":
                    if not mgr.has_relational:
                        return "Procedural memory is not enabled."
                    if not rule_trigger:
                        return "Rule requires 'rule_trigger'."
                    mem = await mgr.add_rule(
                        rule_trigger, content, priority=rule_priority, trigger_keywords=parsed_kw
                    )
                    return f"Rule {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

                if category == "instruction":
                    if not mgr.has_relational:
                        return "Procedural memory is not enabled."
                    mem = await mgr.add_rule(
                        "always", content, priority=max(rule_priority, 10), source=RuleSource.AGENT_SELF
                    )
                    return f"Instruction {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            except Exception as e:
                logger.warning("MCP memory_store failed: %s", e)
                return f"Failed to store memory: {e}"

            return f"Unknown category: {category}"

    def _register_manage(self) -> None:
        mgr = self._manager

        @self._mcp.tool(
            name="memory_manage",
            description=(
                "Update, delete, correct, or rate an existing memory.\n\n"
                "Actions:\n"
                "- update: Change content of an existing memory\n"
                "- delete: Remove a memory permanently\n"
                "- correct: Mark a memory as wrong and store the corrected version "
                "(old memory is demoted, new correction is preferred in future recalls)\n"
                "- rate: Give feedback on a memory (1-5 scale; higher-rated memories "
                "rank higher and resist forgetting)"
            ),
        )
        async def memory_manage(
            action: str,
            memory_id: str,
            category: str,
            new_content: str | None = None,
            new_importance: float | None = None,
            rating_score: int | None = None,
        ) -> str:
            """Manage an existing memory.

            Args:
                action: "update", "delete", "correct", or "rate".
                memory_id: Memory ID from memory_recall results.
                category: knowledge | event | preference | rule (claim/instruction not manageable).
                new_content: Required for update/correct actions.
                new_importance: Optional new importance score (0.0-1.0).
                rating_score: Required for rate action (1-5, 1=bad, 5=excellent).
            """
            valid_actions = ("update", "delete", "correct", "rate")
            if action not in valid_actions:
                return f"Error: invalid action '{action}'. Valid: {', '.join(valid_actions)}"

            valid_manage_cats = ("knowledge", "event", "preference", "rule")
            mem_type = _CATEGORY_TO_TYPE.get(category)
            if mem_type is None or category not in valid_manage_cats:
                return f"Error: invalid category '{category}'. Valid for manage: {', '.join(valid_manage_cats)}"

            try:
                if action == "rate":
                    if rating_score is None:
                        return "Rate requires 'rating_score' (1-5)."
                    if mem_type not in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
                        return "Rate is only supported for knowledge/event memories."
                    if not mgr.has_vector:
                        return f"{category} memory is not enabled."
                    ok = await mgr.rate_memory(memory_id, rating_score)
                    if ok:
                        return f"Memory rated (ID: {memory_id}, score: {rating_score})"
                    return f"Memory not found (ID: {memory_id})"

                if action == "delete":
                    if mem_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
                        if not mgr.has_vector:
                            return f"{category} memory is not enabled."
                        coll = (
                            mgr.config.semantic_collection
                            if mem_type == MemoryType.SEMANTIC
                            else mgr.config.episodic_collection
                        )
                        n = await mgr.delete_memory(coll, [memory_id])
                        return f"Memory deleted (ID: {memory_id})" if n > 0 else f"Memory not found (ID: {memory_id})"
                    if mem_type == MemoryType.PROFILE:
                        return "Profile attributes cannot be deleted via memory_manage."
                    if mem_type == MemoryType.PROCEDURAL:
                        if not mgr.has_relational:
                            return "Procedural memory is not enabled."
                        ok = await mgr.delete_rule(memory_id)
                        return f"Rule deleted (ID: {memory_id})" if ok else f"Rule not found (ID: {memory_id})"

                if action == "update":
                    if not new_content:
                        return "Update requires 'new_content'."
                    updated = await mgr.update_memory(memory_id, content=new_content, importance=new_importance)
                    return f"Memory updated (ID: {updated.id})"

                if action == "correct":
                    if not new_content:
                        return "Correct requires 'new_content' with the corrected fact."
                    if mem_type != MemoryType.SEMANTIC:
                        return "Correct is only supported for knowledge memories."
                    if not mgr.has_vector:
                        return "Knowledge memory is not enabled."
                    correction = await mgr.correct_memory(memory_id, new_content)
                    return (
                        f"Memory corrected: old memory {memory_id} demoted, "
                        f"new correction stored (ID: {correction.id})"
                    )

            except Exception as e:
                logger.warning("MCP memory_manage failed: %s", e)
                return f"Failed to manage memory: {e}"

            return f"Unknown action: {action}"

    # ── Public API ───────────────────────────────────────────────────

    @property
    def mcp(self) -> FastMCP:
        """Access the underlying FastMCP instance for advanced configuration."""
        return self._mcp

    def get_streamable_http_app(self) -> Starlette:
        """Get a Starlette/ASGI app for Streamable HTTP transport.

        Mount this on your FastAPI application:
            app.mount("/mcp", mcp_server.get_streamable_http_app())
        """
        return self._mcp.streamable_http_app()


def create_memory_mcp_server(
    memory_manager: MemoryManager,
    *,
    server_name: str = "myrm-memory",
) -> MemoryMCPServer:
    """Factory: create a MemoryMCPServer from a MemoryManager instance.

    Args:
        memory_manager: The MemoryManager to expose via MCP.
        server_name: MCP server name visible to external agents.

    Returns:
        Configured MemoryMCPServer ready to be mounted.
    """
    return MemoryMCPServer(memory_manager, server_name=server_name)


__all__ = ["MemoryMCPServer", "create_memory_mcp_server"]
