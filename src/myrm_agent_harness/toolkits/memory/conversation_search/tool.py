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

from myrm_agent_harness.toolkits.memory.conversation_search.format_output import format_conversation_search_response
from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    CONVERSATION_SEARCH_TOOL_NAME,
    DEFAULT_CONVERSATION_SEARCH_LIMIT,
    MAX_CONVERSATION_SEARCH_LIMIT,
    ConversationSearchLineage,
    ConversationSearchMode,
    ConversationSearchRequest,
    ConversationSearchScope,
)

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
        return await format_conversation_search_response(response)

    return conversation_search


def _normalize_tool_query(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
