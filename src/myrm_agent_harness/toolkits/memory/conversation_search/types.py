"""Conversation recall DTOs and formatting limits.

[INPUT]
pydantic::BaseModel (POS: validation and serialization layer)

[OUTPUT]
ConversationSearchRequest: typed provider request.
    ConversationSourceRef: UI-safe source reference for one recalled conversation.
    ConversationSearchHit: one conversation-level recall result.
    ConversationIndexCoverage: index coverage and backfill metrics DTO.
    ConversationSearchResponse: provider response envelope.

[POS]
Conversation recall type definitions. Provides storage-agnostic DTOs for exact snippets, precomputed summaries,
ranking metadata, and citation-safe provenance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONVERSATION_SEARCH_TOOL_NAME = "conversation_search_tool"
DEFAULT_CONVERSATION_SEARCH_LIMIT = 5
MAX_CONVERSATION_SEARCH_LIMIT = 8
MAX_SNIPPET_CHARS = 700
MAX_SUMMARY_CHARS = 1200
MAX_TOOL_OUTPUT_CHARS = 6000

ConversationSearchMode = Literal["search", "recent"]
ConversationSearchScope = Literal["current_agent", "same_source", "agent_and_source"]
ConversationSearchLineage = Literal["all", "ancestors", "descendants", "related"]
ConversationSearchSource = Literal["conversation_index", "semantic", "recent", "hybrid"]
ConversationSourceType = Literal["conversation_history"]


class ConversationSourceRef(BaseModel):
    """UI-safe source reference for a recalled conversation."""

    model_config = ConfigDict(extra="forbid")

    type: ConversationSourceType = "conversation_history"
    conversation_id: str
    message_id: str | None = None
    title: str | None = None
    snippet: str = ""
    summary: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    agent_id: str | None = None
    surface: str | None = None
    fork_parent_id: str | None = None
    lineage: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationSearchRequest(BaseModel):
    """Provider request for conversation-level recall."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=500)
    mode: ConversationSearchMode | None = None
    scope: ConversationSearchScope = "current_agent"
    lineage: ConversationSearchLineage = "all"
    limit: int = Field(
        default=DEFAULT_CONVERSATION_SEARCH_LIMIT,
        ge=1,
        le=MAX_CONVERSATION_SEARCH_LIMIT,
    )
    min_score: float = Field(default=0.2, ge=0.0, le=1.0)
    current_conversation_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    expand_conversation_id: str | None = Field(default=None, max_length=255)
    expand_message_id: str | None = Field(default=None, max_length=255)
    expand_window: int = Field(default=5, ge=1, le=20)

    @field_validator("query", mode="before")
    @classmethod
    def _normalize_query(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class ConversationSearchHit(BaseModel):
    """One conversation-level recall hit."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    title: str | None = None
    snippet: str = ""
    summary: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    source: ConversationSearchSource = "conversation_index"
    message_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    source_ref: ConversationSourceRef | None = None


class ConversationIndexCoverage(BaseModel):
    """Index coverage and backfill metrics for the underlying conversation store."""

    model_config = ConfigDict(extra="forbid")

    total_conversations: int = Field(default=0, ge=0, description="Total conversations in canonical store")
    indexed_conversations: int = Field(default=0, ge=0, description="Conversations indexed in FTS/vector index")
    coverage_ratio: float = Field(default=1.0, ge=0.0, le=1.0, description="Fraction of indexed conversations")
    unindexed_recent_count: int = Field(default=0, ge=0, description="Count of unindexed/backfilling conversations")
    indexing_degraded: bool = Field(default=False, description="True if index is rebuilding or degraded")


class ConversationSearchResponse(BaseModel):
    """Conversation search response returned by providers."""

    model_config = ConfigDict(extra="forbid")

    mode: ConversationSearchMode
    hits: list[ConversationSearchHit] = Field(default_factory=list)
    truncated: bool = False
    query: str = ""
    rejected_reason: str | None = None
    coverage: ConversationIndexCoverage | None = Field(default=None, description="Index coverage report if available")
    relaxed: bool = Field(default=False, description="True if query fell back to relaxed CJK token matching")
    query_tokens: list[str] = Field(default_factory=list, description="Effective tokens used for full-text search")
