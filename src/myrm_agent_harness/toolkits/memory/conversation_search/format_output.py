"""Format conversation search hits for agent tool output.

[INPUT]
- toolkits.memory.conversation_search.types::ConversationSearchHit, ConversationSearchResponse (POS: Conversation search DTOs)
- toolkits.memory.agent_surface.memory_recall_formatting (POS: Recall redact → sanitize/preamble helpers)

[OUTPUT]
- format_conversation_search_response: Render hits with conversation_history sources in tool metadata.

[POS]
Agent-facing formatter for memory_search conversation corpus results.
"""

from __future__ import annotations

from datetime import datetime

from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    MAX_SNIPPET_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TOOL_OUTPUT_CHARS,
    ConversationSearchHit,
    ConversationSearchResponse,
)
from myrm_agent_harness.toolkits.memory.agent_surface.tool_result_sources import (
    pack_tool_result_with_sources,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    finalize_recall_tool_output,
    recall_preamble_overhead_chars,
    sanitize_recalled_content,
)


async def format_conversation_search_response(
    response: ConversationSearchResponse,
) -> dict[str, object]:
    """Format provider response with conversation_history sources in metadata."""
    if not response.hits:
        if response.mode == "recent":
            return pack_tool_result_with_sources("No previous conversations found.", [])
        if response.rejected_reason:
            return pack_tool_result_with_sources(response.rejected_reason, [])
        return pack_tool_result_with_sources("No matching conversations found.", [])

    max_output_chars = MAX_TOOL_OUTPUT_CHARS - recall_preamble_overhead_chars()
    lines = [
        (
            "Recent conversations:"
            if response.mode == "recent"
            else f"Conversation search results for: {response.query or ''}"
        )
    ]
    output_chars = sum(len(line) + 1 for line in lines)
    sources: list[dict[str, object]] = []
    truncated = response.truncated

    for index, hit in enumerate(response.hits, start=1):
        block = format_conversation_hit(index, hit)
        block_cost = len(block) + 1
        if output_chars + block_cost > max_output_chars:
            truncated = True
            break
        lines.append(block)
        output_chars += block_cost
        sources.append(source_ref(hit))

    if truncated:
        lines.append("[conversation_search_budget] Results were truncated. Refine the query for more detail.")

    body = finalize_recall_tool_output("\n\n".join(lines))
    return pack_tool_result_with_sources(body, sources)


def format_conversation_hit(index: int, hit: ConversationSearchHit) -> str:
    title = hit.title or "Untitled conversation"
    when = format_time(hit.updated_at or hit.created_at)
    header = f"{index}. {title} (conversation_id: {hit.conversation_id}, score: {hit.score:.2f}, source: {hit.source}"
    if hit.message_id:
        header += f", message_id: {hit.message_id}"
    if when:
        header += f", {when}"
    header += ")"
    snippet = _safe_bounded(hit.snippet, MAX_SNIPPET_CHARS)
    summary = _safe_bounded(hit.summary or "", MAX_SUMMARY_CHARS)
    parts = [header]
    if summary:
        parts.append(f"summary: {summary}")
    if snippet:
        parts.append(f"snippet: {snippet}")
    return "\n".join(parts)


def source_ref(hit: ConversationSearchHit) -> dict[str, object]:
    if hit.source_ref is not None:
        ref = hit.source_ref.model_dump(mode="json", exclude_none=True)
    else:
        ref = {
            "type": "conversation_history",
            "conversation_id": hit.conversation_id,
            "message_id": hit.message_id,
            "title": hit.title,
            "snippet": _safe_bounded(hit.snippet, MAX_SNIPPET_CHARS),
            "summary": _safe_bounded(hit.summary or "", MAX_SUMMARY_CHARS) or None,
            "score": round(hit.score, 4),
            "created_at": hit.created_at.isoformat() if hit.created_at else None,
            "updated_at": hit.updated_at.isoformat() if hit.updated_at else None,
        }
    ref["source_key"] = f"conversation:{hit.conversation_id}:{hit.message_id or ''}"
    return {key: value for key, value in ref.items() if value is not None}


def _safe_bounded(text: str, max_chars: int) -> str:
    bounded_text = bounded(text, max_chars)
    if not bounded_text:
        return ""
    return sanitize_recalled_content(bounded_text)


def bounded(text: str, max_chars: int) -> str:
    value = " ".join(text.split())
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}..."


def format_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()
