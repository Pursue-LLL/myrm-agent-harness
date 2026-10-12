"""memory_recall MCP tool: semantic search with category / time / profile filters.

[INPUT]
- toolkits.memory.agent_surface.memory_recall_formatting (POS: recall sanitize / label / footer SSOT)
- toolkits.memory.agent_surface.memory_recall_budget (POS: recall output budget guardrails)
- toolkits.memory.types::MemorySearchResult (POS: ranked search hit)

[OUTPUT]
- register_recall_tool: register memory_recall on an MCPServer

[POS]
Read plane of the MCP adapter. Recalled bodies are sanitized and followed by a static untrusted advisory.
"""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.common import (
    CATEGORY_TO_TYPE,
    ManagerResolver,
    parse_string_list,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_budget import (
    MAX_RECALL_OUTPUT_CHARS,
    budget_recall_line,
    line_cost,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    RECALL_DRIFT_DEFENSE_FOOTER,
    finalize_recall_tool_output,
    format_profile_recall_output,
    format_recall_source_error_suffix,
    memory_age_label,
    recall_drift_defense_footer_chars,
    recall_preamble_overhead_chars,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    channel_label as _channel_label,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    is_stale as _is_stale,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    parse_time_bound as _parse_time_bound,
)
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)

_RECALL_DESCRIPTION = (
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
)


def _recall_line_parts(result: MemorySearchResult) -> tuple[str, str]:
    """Build the provenance prefix and the claim / source-error / staleness suffix of one hit."""
    mem = result.memory
    category = next(
        (name for name, mem_type in CATEGORY_TO_TYPE.items() if mem_type == result.memory_type),
        result.memory_type.value,
    )
    age = memory_age_label(mem.created_at)
    provenance = _channel_label(mem.scope.channel_id)
    prefix = f"{provenance}[{category}] (id: {mem.id}, score: {result.score:.2f}, {age}) "

    suffix = ""
    if isinstance(mem, ClaimMemory):
        relation_type = str(mem.metadata.get("latest_relationship_type", "")).strip().lower()
        relation_suffix = f" relation={relation_type}" if relation_type else ""
        suffix += (
            f" [claim_graph freshness={mem.freshness} contradiction={mem.contradiction_status} "
            f"evidence={mem.evidence_count}{relation_suffix}]"
        )
    if isinstance(mem, SemanticMemory) and mem.source_error:
        suffix += format_recall_source_error_suffix(mem.source_error)
    if result.memory_type in (
        MemoryType.SEMANTIC,
        MemoryType.EPISODIC,
        MemoryType.CLAIM,
    ) and _is_stale(mem.created_at):
        suffix += " (may be outdated — verify before citing)"
    return prefix, suffix


def _format_recall_results(results: Sequence[MemorySearchResult]) -> str:
    """Render hits within the recall output budget, then add the untrusted-content advisory."""
    output: list[str] = []
    max_body_chars = MAX_RECALL_OUTPUT_CHARS - recall_drift_defense_footer_chars() - recall_preamble_overhead_chars()
    output_chars = 0
    truncated_by_budget = False

    for result in results:
        prefix, suffix = _recall_line_parts(result)
        budgeted = budget_recall_line(
            prefix=prefix,
            content=result.content,
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

    return finalize_recall_tool_output("\n".join(output)) + RECALL_DRIFT_DEFENSE_FOOTER


def register_recall_tool(mcp: MCPServer, resolve: ManagerResolver) -> None:
    """Register memory_recall on ``mcp``; ``resolve`` supplies the request's MemoryManager."""

    @mcp.tool(name="memory_recall", description=_RECALL_DESCRIPTION)
    async def memory_recall(
        query: str,
        categories: str | list[str] | None = None,
        limit: int = 5,
        profile_key: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        """Recall memories matching a natural language query.

        Args:
            query: Semantic search query. Be specific for better results.
            categories: Filter: knowledge, claim, event, preference, rule.
                Accepts a comma-separated string, a JSON array, or a raw list.
                None = all types.
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

        parsed_cats = parse_string_list(categories)
        types: list[MemoryType] | None = None
        if parsed_cats:
            valid = [CATEGORY_TO_TYPE[c] for c in parsed_cats if c in CATEGORY_TO_TYPE]
            types = valid or None

        results = await mgr.search(
            query,
            memory_types=types,
            limit=normalize_recall_limit(limit),
            since=_parse_time_bound(since),
            until=_parse_time_bound(until),
        )
        if not results:
            if mgr.last_retrieval_trace is not None and mgr.last_retrieval_trace.degraded:
                return "Memory search timed out. Try a more specific query or retry."
            return "No relevant memories found."

        return _format_recall_results(results)
