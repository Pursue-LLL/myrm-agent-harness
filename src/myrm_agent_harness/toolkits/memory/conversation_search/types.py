"""Conversation recall DTOs and formatting limits.

[INPUT]
pydantic::BaseModel (POS: validation and serialization layer)

[OUTPUT]
ConversationSearchRequest: typed provider request.
    ConversationSourceRef: UI-safe source reference for one recalled conversation.
    ConversationSearchHit: one conversation-level recall result.
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
    limit: int = Field(default=DEFAULT_CONVERSATION_SEARCH_LIMIT, ge=1, le=MAX_CONVERSATION_SEARCH_LIMIT)
    min_score: float = Field(default=0.2, ge=0.0, le=1.0)
    current_conversation_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None

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


class ConversationSearchResponse(BaseModel):
    """Conversation search response returned by providers."""

    model_config = ConfigDict(extra="forbid")

    mode: ConversationSearchMode
    hits: list[ConversationSearchHit] = Field(default_factory=list)
    truncated: bool = False
    query: str = ""
    rejected_reason: str | None = None
