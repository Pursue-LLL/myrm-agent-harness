"""Agent tool factory for conversation recall.

[INPUT]
myrm_agent_harness.toolkits.memory.protocols.conversation_search::ConversationSearchProtocol (POS: conversation search protocol boundary)
myrm_agent_harness.toolkits.memory.conversation_search.types (POS: conversation recall DTOs)

[OUTPUT]
create_conversation_search_tool: build an agent-callable conversation_search tool.

[POS]
Framework-level conversation recall tool factory. It formats provider results into compact evidence-oriented
tool output without calling an LLM or depending on business storage.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    CONVERSATION_SEARCH_TOOL_NAME,
    DEFAULT_CONVERSATION_SEARCH_LIMIT,
    MAX_CONVERSATION_SEARCH_LIMIT,
    MAX_SNIPPET_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TOOL_OUTPUT_CHARS,
    ConversationSearchHit,
    ConversationSearchLineage,
    ConversationSearchMode,
    ConversationSearchRequest,
    ConversationSearchScope,
)
from myrm_agent_harness.toolkits.memory.memory_citations import emit_sources

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.conversation_search import ConversationSearchProtocol


class ConversationSearchInput(BaseModel):
    """Input schema for conversation_search."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        default="",
        description=(
            "Search query for previous conversations. Use an empty string or '*' to browse recent conversations."
        ),
        max_length=500,
    )
    limit: int = Field(default=DEFAULT_CONVERSATION_SEARCH_LIMIT, ge=1, le=MAX_CONVERSATION_SEARCH_LIMIT)
    mode: ConversationSearchMode | None = Field(
        default=None,
        description="Optional mode: 'search' or 'recent'. Empty query and '*' automatically use recent mode.",
    )
    scope: ConversationSearchScope = Field(
        default="current_agent",
        description="Recall scope: current_agent, same_source, or agent_and_source.",
    )
    lineage: ConversationSearchLineage = Field(
        default="all",
        description="Optional fork lineage filter: all, ancestors, descendants, or related.",
    )
    min_score: float = Field(default=0.2, ge=0.0, le=1.0)
    since: datetime | None = None
    until: datetime | None = None

    @field_validator("query", mode="before")
    @classmethod
    def _normalize_query(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


def create_conversation_search_tool(provider: ConversationSearchProtocol) -> object:
    """Create the conversation_search agent tool."""

    @tool(CONVERSATION_SEARCH_TOOL_NAME, args_schema=ConversationSearchInput)
    async def conversation_search(
        query: str = "",
        limit: int = DEFAULT_CONVERSATION_SEARCH_LIMIT,
        mode: ConversationSearchMode | None = None,
        scope: ConversationSearchScope = "current_agent",
        lineage: ConversationSearchLineage = "all",
        min_score: float = 0.2,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> str:
        """Search prior conversations for exact evidence and precomputed summaries.

        Use when the user refers to earlier chats, prior decisions, previous constraints, customer context,
        or asks to continue something discussed before. Use an empty query or "*" to browse recent
        conversations. This tool does not summarize with an LLM; it returns stored snippets and summaries.
        """

        query_text = _normalize_tool_query(query)
        requested_mode = "recent" if query_text == "*" else mode
        request = ConversationSearchRequest(
            query="" if query_text == "*" else query_text,
            mode=requested_mode,
            scope=scope,
            lineage=lineage,
            limit=limit,
            min_score=min_score,
            since=since,
            until=until,
        )
        response = await provider.search(request)
        if not response.hits:
            if response.mode == "recent":
                return "No previous conversations found."
            if response.rejected_reason:
                return response.rejected_reason
            return "No matching conversations found."

        lines = [
            (
                "Recent conversations:"
                if response.mode == "recent"
                else f"Conversation search results for: {response.query or query}"
            )
        ]
        output_chars = sum(len(line) + 1 for line in lines)
        sources: list[dict[str, object]] = []
        truncated = response.truncated

        for index, hit in enumerate(response.hits, start=1):
            block = _format_hit(index, hit)
            block_cost = len(block) + 1
            if output_chars + block_cost > MAX_TOOL_OUTPUT_CHARS:
                truncated = True
                break
            lines.append(block)
            output_chars += block_cost
            sources.append(_source_ref(len(sources) + 1, hit))

        if truncated:
            lines.append("[conversation_search_budget] Results were truncated. Refine the query for more detail.")

        await emit_sources(sources)
        return "\n\n".join(lines)

    return conversation_search


def _format_hit(index: int, hit: ConversationSearchHit) -> str:
    title = hit.title or "Untitled conversation"
    when = _format_time(hit.updated_at or hit.created_at)
    header = f"{index}. {title} (conversation_id: {hit.conversation_id}, score: {hit.score:.2f}, source: {hit.source}"
    if when:
        header += f", {when}"
    header += ")"
    snippet = _bounded(hit.snippet, MAX_SNIPPET_CHARS)
    summary = _bounded(hit.summary or "", MAX_SUMMARY_CHARS)
    parts = [header]
    if summary:
        parts.append(f"summary: {summary}")
    if snippet:
        parts.append(f"snippet: {snippet}")
    return "\n".join(parts)


def _source_ref(index: int, hit: ConversationSearchHit) -> dict[str, object]:
    if hit.source_ref is not None:
        ref = hit.source_ref.model_dump(mode="json", exclude_none=True)
    else:
        ref = {
            "type": "conversation_history",
            "conversation_id": hit.conversation_id,
            "message_id": hit.message_id,
            "title": hit.title,
            "snippet": _bounded(hit.snippet, MAX_SNIPPET_CHARS),
            "summary": _bounded(hit.summary or "", MAX_SUMMARY_CHARS) or None,
            "score": round(hit.score, 4),
            "created_at": hit.created_at.isoformat() if hit.created_at else None,
            "updated_at": hit.updated_at.isoformat() if hit.updated_at else None,
        }
    ref["index"] = index
    ref["source_key"] = f"conversation:{hit.conversation_id}:{hit.message_id or ''}"
    return {key: value for key, value in ref.items() if value is not None}


def _normalize_tool_query(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bounded(text: str, max_chars: int) -> str:
    value = " ".join(text.split())
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}..."


def _format_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()
