"""memory_list MCP tool: query-free enumeration and audit of stored memories.

[INPUT]
- toolkits.memory.agent_surface.mcp_server.common::{CATEGORY_TO_TYPE, ManagerResolver} (POS: Stateless helpers for the recall/list/store/manage tool handlers)
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager)
- toolkits.memory.types::MemoryType (POS: memory type enum)
- toolkits.memory.agent_surface.memory_recall_formatting (POS: recall sanitize / age label / footer SSOT)
- toolkits.memory.agent_surface.memory_recall_budget (POS: recall output budget guardrails)

[OUTPUT]
- register_list_tool: register memory_list on an MCPServer

[POS]
Browsing counterpart of memory_recall for auditing and cleanup; output is sanitized like recall output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer

from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.common import CATEGORY_TO_TYPE, ManagerResolver
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_budget import (
    MAX_RECALL_OUTPUT_CHARS,
    budget_recall_line,
    line_cost,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    RECALL_DRIFT_DEFENSE_FOOTER,
    finalize_recall_tool_output,
    memory_age_label,
    recall_drift_defense_footer_chars,
    recall_preamble_overhead_chars,
    sanitize_recalled_content,
)
from myrm_agent_harness.toolkits.memory.types import MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

_LIST_DESCRIPTION = (
    "Browse and audit stored memories by category. Unlike memory_recall "
    "(which requires a search query), memory_list enumerates memories "
    "without any query — useful for auditing, cleanup, or exploring what "
    "the memory system contains.\n\n"
    "Modes:\n"
    "- No category: returns an overview with per-category counts and a "
    "preview of the most recent items in each category\n"
    "- With category: returns paginated memories of that specific type\n\n"
    "Categories: knowledge, claim, event, preference, rule"
)

_OVERVIEW_PREVIEW_LIMIT = 3


async def _list_overview(mgr: MemoryManager, *, include_archived: bool) -> str:
    """Build a statistical overview with top-N preview per category."""
    lines: list[str] = ["# Memory Overview", ""]
    total = 0

    for cat, mem_type in CATEGORY_TO_TYPE.items():
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
            limit=_OVERVIEW_PREVIEW_LIMIT,
            include_archived=include_archived,
        )
        for mem in items:
            age = memory_age_label(mem.created_at)
            safe_content = sanitize_recalled_content(mem.content)
            snippet = safe_content[:80] + ("…" if len(safe_content) > 80 else "")
            lines.append(f"  - [{age}] (id: {mem.id}) {snippet}")
        if count > _OVERVIEW_PREVIEW_LIMIT:
            lines.append(
                f'  ... and {count - _OVERVIEW_PREVIEW_LIMIT} more — use memory_list(category="{cat}") to browse'
            )

    lines.insert(1, f"Total memories: {total}")
    lines.append("")
    lines.append(RECALL_DRIFT_DEFENSE_FOOTER)
    return finalize_recall_tool_output("\n".join(lines))


async def _list_category(
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
    max_body = MAX_RECALL_OUTPUT_CHARS - recall_drift_defense_footer_chars() - recall_preamble_overhead_chars()
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
        lines.append("[list_budget] Some entries truncated. Reduce page_size for full content.")

    if page < total_pages:
        lines.append(f'\nNext: memory_list(category="{category}", page={page + 1})')

    lines.append(RECALL_DRIFT_DEFENSE_FOOTER)
    return finalize_recall_tool_output("\n".join(lines))


def register_list_tool(mcp: MCPServer, resolve: ManagerResolver) -> None:
    """Register memory_list on ``mcp``; ``resolve`` supplies the request's MemoryManager."""

    @mcp.tool(name="memory_list", description=_LIST_DESCRIPTION)
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
            mem_type = CATEGORY_TO_TYPE.get(category)
            if mem_type is None:
                valid = ", ".join(CATEGORY_TO_TYPE)
                return f"Error: invalid category '{category}'. Valid: {valid}"
            return await _list_category(
                mgr,
                mem_type,
                category,
                page=page,
                page_size=page_size,
                include_archived=include_archived,
            )

        return await _list_overview(mgr, include_archived=include_archived)
