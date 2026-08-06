"""Memory MCP Server Adapter.

Wraps MemoryManager as an MCP server exposing memory tools
(recall, list, store, manage) to external agents (Claude Code, Cursor, etc.)
via the Model Context Protocol.

Tools extend the internal agent tools in ``memory_agent_tools.py`` with a
dedicated ``memory_list`` enumeration tool for browsing and auditing memories
without a search query.

[INPUT]
- myrm_agent_harness.toolkits.memory.manager::MemoryManager (POS: Unified memory manager)
- myrm_agent_harness.toolkits.memory.types::MemoryType, SemanticMemory (POS: Memory type system)
- myrm_agent_harness.toolkits.memory.memory_recall_formatting (POS: Shared formatting helpers)
- myrm_agent_harness.toolkits.memory._memory_agent_tool_descriptions (POS: LLM-visible memory tool description SSOT)
- myrm_agent_harness.toolkits.memory.memory_recall_budget (POS: Output budget guardrails)

- myrm_agent_harness.toolkits.memory.wiki_memory_boundary (POS: Wiki-memory write boundary heuristics)

[OUTPUT]
- MemoryMCPServer: MCP server adapter exposing memory tools
- create_memory_mcp_server: Factory function
- set_request_memory_manager / reset_request_memory_manager: Per-request manager scoping
- set_request_wiki_boundary_enabled / reset_request_wiki_boundary_enabled: Per-request wiki guard flag

[POS]
MCP server adapter that lets external AI agents (Claude Code, Cursor, Codex)
access the memory system via standard MCP protocol. Four MCP tools:
recall (semantic search with categories/time/profile), list (enumeration
and audit), store (5 categories), and manage (update/delete/correct/rate).
`memory_manage` and `memory_store` descriptions import `_memory_agent_tool_descriptions`
SSOT with `surface="mcp"`; recall/list descriptions remain MCP-specific inline.
Supports optional manager_resolver for per-request dynamic scoping
(e.g. per-token agent binding via ContextVar).
Recall/list tool output sanitizes recalled bodies and prefixes a static untrusted advisory.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from mcp.server import MCPServer
from starlette.applications import Starlette

from myrm_agent_harness.toolkits.memory._memory_agent_tool_descriptions import (
    build_mcp_memory_store_tool_description,
    resolve_memory_manage_tool_description,
)
from myrm_agent_harness.toolkits.memory.memory_recall_budget import (
    MAX_RECALL_OUTPUT_CHARS,
    budget_recall_line,
    line_cost,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    RECALL_DRIFT_DEFENSE_FOOTER,
    channel_label as _channel_label,
    finalize_recall_tool_output,
    format_profile_recall_output,
    is_stale as _is_stale,
    memory_age_label,
    parse_time_bound as _parse_time_bound,
    recall_drift_defense_footer_chars,
    recall_preamble_overhead_chars,
    sanitize_recalled_content,
)
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    MemoryType,
    RuleSource,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.memory.wiki_memory_boundary import (
    looks_like_wiki_document,
    record_wiki_memory_save_rejection,
    wiki_memory_save_rejection_message,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_request_memory_manager: ContextVar[MemoryManager | None] = ContextVar(
    "myrm_mcp_request_memory_manager",
    default=None,
)
_request_wiki_boundary_enabled: ContextVar[bool] = ContextVar(
    "myrm_mcp_request_wiki_boundary_enabled",
    default=False,
)


def set_request_memory_manager(
    manager: MemoryManager | None,
) -> Token[MemoryManager | None]:
    """Bind the MemoryManager used by MCP tool handlers for the current request."""
    return _request_memory_manager.set(manager)


def reset_request_memory_manager(token: Token[MemoryManager | None]) -> None:
    """Restore the previous MemoryManager binding after a request completes."""
    _request_memory_manager.reset(token)


def set_request_wiki_boundary_enabled(enabled: bool) -> Token[bool]:
    """Bind whether wiki document-like payloads should be rejected on memory_store."""
    return _request_wiki_boundary_enabled.set(enabled)


def reset_request_wiki_boundary_enabled(token: Token[bool]) -> None:
    """Restore the previous wiki boundary flag after a request completes."""
    _request_wiki_boundary_enabled.reset(token)


def get_request_wiki_boundary_enabled() -> bool:
    """Return the active wiki boundary flag for the current MCP request."""
    return _request_wiki_boundary_enabled.get()


_CATEGORY_TO_TYPE: dict[str, MemoryType] = {
    "knowledge": MemoryType.SEMANTIC,
    "claim": MemoryType.CLAIM,
    "event": MemoryType.EPISODIC,
    "preference": MemoryType.PROFILE,
    "rule": MemoryType.PROCEDURAL,
    "instruction": MemoryType.PROCEDURAL,
}


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

    Provides memory_recall, memory_list, memory_store, and memory_manage
    tools that external agents can invoke via MCP protocol.

    Supports two modes:
    - Fixed: a single MemoryManager bound at construction.
    - Resolver: a callable that returns the MemoryManager for the current
      request context (e.g. per-token agent scoping via ContextVar).

    Usage:
        # Fixed mode
        mcp_server = MemoryMCPServer(manager)

        # Resolver mode (multi-scope)
        mcp_server = MemoryMCPServer(manager, manager_resolver=my_resolver)
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        server_name: str = "myrm-memory",
        manager_resolver: Callable[[], MemoryManager] | None = None,
    ) -> None:
        self._default_manager = memory_manager
        self._manager_resolver = manager_resolver
        self._store_tool_description = build_mcp_memory_store_tool_description(
            wiki_boundary_in_description=True,
            approval_required=memory_manager.approval_required,
        )
        self._manage_tool_description = resolve_memory_manage_tool_description(
            surface="mcp",
        )
        self._mcp = MCPServer(
            server_name,
            instructions=(
                "Memory service for storing, recalling, listing, and managing user "
                "knowledge, preferences, and project context. Use memory_recall to "
                "search by query. Use memory_list to browse or audit memories by "
                "category. Use memory_store to save important facts. Use "
                "memory_manage to correct, rate, update, or delete memories."
            ),
        )
        self._register_tools()

    def _resolve_manager(self) -> MemoryManager:
        """Return the active MemoryManager for the current request context."""
        bound = _request_memory_manager.get()
        if bound is not None:
            return bound
        if self._manager_resolver is not None:
            return self._manager_resolver()
        return self._default_manager

    # ── Tool Registration ────────────────────────────────────────────

    def _register_tools(self) -> None:
        """Register memory tools on the MCP server."""
        self._register_recall()
        self._register_list()
        self._register_store()
        self._register_manage()

    def _register_recall(self) -> None:
        resolve = self._resolve_manager

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
            mgr = resolve()
            if profile_key:
                if not mgr.has_relational:
                    return "Profile memory is not enabled."
                value = await mgr.get_profile_attribute(profile_key)
                if value is None:
                    return f"No profile attribute '{profile_key}' found."
                return format_profile_recall_output(profile_key, value)

            parsed_cats = _parse_string_list(categories)
            types: list[MemoryType] | None = None
            if parsed_cats:
                valid = [
                    _CATEGORY_TO_TYPE[c] for c in parsed_cats if c in _CATEGORY_TO_TYPE
                ]
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
            max_body_chars = (
                MAX_RECALL_OUTPUT_CHARS
                - recall_drift_defense_footer_chars()
                - recall_preamble_overhead_chars()
            )
            output_chars = 0
            truncated_by_budget = False

            for r in results:
                cat = next(
                    (k for k, v in _CATEGORY_TO_TYPE.items() if v == r.memory_type),
                    r.memory_type.value,
                )
                mem = r.memory
                age = memory_age_label(mem.created_at)
                provenance = _channel_label(mem.scope.channel_id)
                prefix = (
                    f"{provenance}[{cat}] (id: {mem.id}, score: {r.score:.2f}, {age}) "
                )
                suffix = ""
                if isinstance(mem, ClaimMemory):
                    freshness = mem.freshness
                    contradiction = mem.contradiction_status
                    evidence_count = mem.evidence_count
                    relation_type = (
                        str(mem.metadata.get("latest_relationship_type", ""))
                        .strip()
                        .lower()
                    )
                    relation_suffix = (
                        f" relation={relation_type}" if relation_type else ""
                    )
                    suffix += (
                        f" [claim_graph freshness={freshness} contradiction={contradiction} "
                        f"evidence={evidence_count}{relation_suffix}]"
                    )
                if isinstance(mem, SemanticMemory) and mem.source_error:
                    suffix += f" (avoid: {mem.source_error})"
                if r.memory_type in (
                    MemoryType.SEMANTIC,
                    MemoryType.EPISODIC,
                    MemoryType.CLAIM,
                ) and _is_stale(mem.created_at):
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

            text = finalize_recall_tool_output("\n".join(output))
            text += RECALL_DRIFT_DEFENSE_FOOTER
            return text

    def _register_list(self) -> None:
        resolve = self._resolve_manager

        @self._mcp.tool(
            name="memory_list",
            description=(
                "Browse and audit stored memories by category. Unlike memory_recall "
                "(which requires a search query), memory_list enumerates memories "
                "without any query — useful for auditing, cleanup, or exploring what "
                "the memory system contains.\n\n"
                "Modes:\n"
                "- No category: returns an overview with per-category counts and a "
                "preview of the most recent items in each category\n"
                "- With category: returns paginated memories of that specific type\n\n"
                "Categories: knowledge, claim, event, preference, rule"
            ),
        )
        async def memory_list(
            category: str | None = None,
            page: int = 1,
            page_size: int = 20,
            include_archived: bool = False,
        ) -> str:
            """List memories by category or get an overview of all categories.

            Args:
                category: Filter to one category (knowledge, claim, event,
                    preference, rule). None = overview of all categories.
                page: Page number (1-based, default 1). Only used with category.
                page_size: Items per page (1-50, default 20). Only used with category.
                include_archived: Include archived/disabled memories (default False).
            """
            page_size = max(1, min(page_size, 50))
            page = max(1, page)

            mgr = resolve()
            if category is not None:
                mem_type = _CATEGORY_TO_TYPE.get(category)
                if mem_type is None:
                    valid = ", ".join(_CATEGORY_TO_TYPE)
                    return f"Error: invalid category '{category}'. Valid: {valid}"
                return await self._list_category(
                    mgr,
                    mem_type,
                    category,
                    page=page,
                    page_size=page_size,
                    include_archived=include_archived,
                )

            return await self._list_overview(mgr, include_archived=include_archived)

    async def _list_overview(
        self,
        mgr: MemoryManager,
        *,
        include_archived: bool,
    ) -> str:
        """Build a statistical overview with top-N preview per category."""
        lines: list[str] = ["# Memory Overview", ""]
        total = 0
        preview_limit = 3

        for cat, mem_type in _CATEGORY_TO_TYPE.items():
            if cat == "instruction":
                continue
            count = await mgr.count_memories(mem_type)
            total += count
            lines.append(f"## {cat} ({count})")
            if count == 0:
                lines.append("  (empty)")
                continue
            items = await mgr.list_memories(
                mem_type,
                limit=preview_limit,
                include_archived=include_archived,
            )
            for mem in items:
                age = memory_age_label(mem.created_at)
                safe_content = sanitize_recalled_content(mem.content)
                snippet = safe_content[:80] + ("…" if len(safe_content) > 80 else "")
                lines.append(f"  - [{age}] (id: {mem.id}) {snippet}")
            if count > preview_limit:
                lines.append(
                    f'  ... and {count - preview_limit} more — use memory_list(category="{cat}") to browse'
                )

        lines.insert(1, f"Total memories: {total}")
        lines.append("")
        lines.append(RECALL_DRIFT_DEFENSE_FOOTER)
        return finalize_recall_tool_output("\n".join(lines))

    async def _list_category(
        self,
        mgr: MemoryManager,
        mem_type: MemoryType,
        category: str,
        *,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> str:
        """Paginated listing for a single category."""
        count = await mgr.count_memories(mem_type)
        offset = (page - 1) * page_size
        total_pages = max(1, (count + page_size - 1) // page_size)

        if offset >= count and count > 0:
            return f"Page {page} is beyond the last page ({total_pages}). Use page=1..{total_pages}."

        items = await mgr.list_memories(
            mem_type,
            limit=page_size,
            offset=offset,
            include_archived=include_archived,
        )

        lines: list[str] = [
            f"# {category} — page {page}/{total_pages} ({count} total)",
            "",
        ]
        max_body = (
            MAX_RECALL_OUTPUT_CHARS
            - recall_drift_defense_footer_chars()
            - recall_preamble_overhead_chars()
        )
        char_count = sum(line_cost(ln) for ln in lines)
        truncated = False

        for mem in items:
            age = memory_age_label(mem.created_at)
            prefix = f"[{age}] (id: {mem.id}) "
            budgeted = budget_recall_line(
                prefix=prefix,
                content=mem.content,
                suffix="",
                output_chars=char_count,
                max_body_chars=max_body,
            )
            if budgeted.line is None:
                truncated = True
                break
            lines.append(budgeted.line)
            char_count = budgeted.next_chars
            truncated = truncated or budgeted.truncated

        if truncated:
            lines.append(
                "[list_budget] Some entries truncated. Reduce page_size for full content."
            )

        if page < total_pages:
            lines.append(f'\nNext: memory_list(category="{category}", page={page + 1})')

        lines.append(RECALL_DRIFT_DEFENSE_FOOTER)
        return finalize_recall_tool_output("\n".join(lines))

    def _register_store(self) -> None:
        resolve = self._resolve_manager

        @self._mcp.tool(
            name="memory_store",
            description=self._store_tool_description,
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

            valid_categories = (
                "knowledge",
                "event",
                "preference",
                "rule",
                "instruction",
            )
            if category not in valid_categories:
                return f"Error: invalid category '{category}'. Valid: {', '.join(valid_categories)}"
            if write_target not in ("bound", "shared"):
                return "Error: write_target must be 'bound' or 'shared'."

            mgr = resolve()
            parsed_tags = _parse_string_list(tags)
            parsed_kw = _parse_string_list(rule_keywords)
            pending = mgr.approval_required

            if (
                get_request_wiki_boundary_enabled()
                and category in ("knowledge", "event")
                and looks_like_wiki_document(content)
            ):
                record_wiki_memory_save_rejection()
                return wiki_memory_save_rejection_message()

            try:
                if category == "knowledge":
                    if not mgr.has_vector:
                        return "Knowledge memory is not enabled."
                    mem = await mgr.add_knowledge(
                        content,
                        importance=importance,
                        tags=parsed_tags,
                        write_target=write_target,
                    )
                    return f"Knowledge {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

                if category == "event":
                    if not mgr.has_vector:
                        return "Event memory is not enabled."
                    mem = await mgr.add_event(
                        content,
                        event_type="agent_observation",
                        write_target=write_target,
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
                        rule_trigger,
                        content,
                        priority=rule_priority,
                        trigger_keywords=parsed_kw,
                    )
                    return f"Rule {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

                if category == "instruction":
                    if not mgr.has_relational:
                        return "Procedural memory is not enabled."
                    mem = await mgr.add_rule(
                        "always",
                        content,
                        priority=max(rule_priority, 10),
                        source=RuleSource.AGENT_SELF,
                    )
                    return f"Instruction {'submitted for approval' if pending else 'stored'} (ID: {mem.id})"

            except Exception as e:
                logger.warning("MCP memory_store failed: %s", e)
                return "Failed to store memory"

            return f"Unknown category: {category}"

    def _register_manage(self) -> None:
        resolve = self._resolve_manager

        @self._mcp.tool(
            name="memory_manage",
            description=self._manage_tool_description,
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
                category: knowledge | event | preference | rule (instruction saves use category=rule).
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

            mgr = resolve()
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
                        return (
                            f"Memory deleted (ID: {memory_id})"
                            if n > 0
                            else f"Memory not found (ID: {memory_id})"
                        )
                    if mem_type == MemoryType.PROFILE:
                        return "Profile attributes cannot be deleted via memory_manage."
                    if mem_type == MemoryType.PROCEDURAL:
                        if not mgr.has_relational:
                            return "Procedural memory is not enabled."
                        ok = await mgr.delete_rule(memory_id)
                        return (
                            f"Rule deleted (ID: {memory_id})"
                            if ok
                            else f"Rule not found (ID: {memory_id})"
                        )

                if action == "update":
                    if not new_content:
                        return "Update requires 'new_content'."
                    updated = await mgr.update_memory(
                        memory_id, content=new_content, importance=new_importance
                    )
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
                        f"Memory corrected (new ID: {correction.id}). "
                        f"Prior entry {memory_id} kept in history."
                    )

            except Exception as e:
                logger.warning("MCP memory_manage failed: %s", e)
                return "Failed to manage memory"

            return f"Unknown action: {action}"

    # ── Public API ───────────────────────────────────────────────────

    @property
    def mcp(self) -> MCPServer:
        """Access the underlying MCPServer instance for advanced configuration."""
        return self._mcp

    def get_streamable_http_app(self, *, stateless: bool = False) -> Starlette:
        """Get a Starlette/ASGI app for Streamable HTTP transport.

        Args:
            stateless: When True, each request creates a fresh transport with
                no session tracking (no ``Mcp-Session-Id``). Appropriate when
                tools are inherently per-request (e.g. auth via Bearer token +
                ContextVar scoping) and no cross-request session state is needed.

        Mount this on your FastAPI application:
            app.mount("/mcp", mcp_server.get_streamable_http_app(stateless=True))
        """
        return self._mcp.streamable_http_app(stateless_http=stateless)


def create_memory_mcp_server(
    memory_manager: MemoryManager,
    *,
    server_name: str = "myrm-memory",
    manager_resolver: Callable[[], MemoryManager] | None = None,
) -> MemoryMCPServer:
    """Factory: create a MemoryMCPServer from a MemoryManager instance.

    Args:
        memory_manager: The default MemoryManager to expose via MCP.
        server_name: MCP server name visible to external agents.
        manager_resolver: Optional callable returning the MemoryManager for the
            current request context. When provided, tool calls resolve the
            manager dynamically (e.g. per-token agent scoping).

    Returns:
        Configured MemoryMCPServer ready to be mounted.
    """
    return MemoryMCPServer(
        memory_manager,
        server_name=server_name,
        manager_resolver=manager_resolver,
    )


__all__ = [
    "MemoryMCPServer",
    "create_memory_mcp_server",
    "get_request_wiki_boundary_enabled",
    "reset_request_memory_manager",
    "reset_request_wiki_boundary_enabled",
    "set_request_memory_manager",
    "set_request_wiki_boundary_enabled",
]
