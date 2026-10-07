"""Types and models for Full Archive Searchable History Meta-Tool.

Part of Item 127: FullArchiveSearchableHistoryMetaTool.
Provides models for archived historical conversation turns, search filters, and relevance results.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ArchiveMessageRoleKind: Origin role for an archived message in history.
- ArchivedMessageRecord: Immutable record of an archived message turn.
- ArchiveSearchFilter: Criteria to restrict historical dialogue search queries.
- ArchiveSearchResultItem: Ranked search result item containing the archived record and match context.
- ArchiveSearchResponse: Consolidated response delivered to the inquiring agent.

[POS]
Types and models for Full Archive Searchable History Meta-Tool.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ArchiveMessageRoleKind(StrEnum):
    """Origin role for an archived message in history."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"
    ERROR_LOG = "error_log"


class ArchivedMessageRecord(BaseModel):
    """Immutable record of an archived message turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str = Field(description="Unique record identifier")
    session_id: str = Field(description="Originating session identifier")
    turn_index: int = Field(ge=0, description="Sequential turn index within the session")
    role: ArchiveMessageRoleKind = Field(description="Message role kind")
    content: str = Field(description="Complete raw content of the turn")
    timestamp_iso: str = Field(description="ISO-8601 recording timestamp")
    metadata: dict[str, str] = Field(default_factory=dict, description="Arbitrary string metadata attributes")


class ArchiveSearchFilter(BaseModel):
    """Criteria to restrict historical dialogue search queries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str | None = Field(default=None, description="Optional target session filter")
    role_filters: list[ArchiveMessageRoleKind] | None = Field(
        default=None,
        description="Optional allowed message role types",
    )
    turn_range_start: int | None = Field(default=None, ge=0, description="Minimum turn index inclusive")
    turn_range_end: int | None = Field(default=None, ge=0, description="Maximum turn index inclusive")
    max_results: int = Field(default=5, gt=0, le=50, description="Maximum number of hits returned")


class ArchiveSearchResultItem(BaseModel):
    """Ranked search result item containing the archived record and match context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: ArchivedMessageRecord = Field(description="Matched immutable message record")
    match_score: float = Field(ge=0.0, description="Relative relevance score")
    relevance_snippet: str = Field(description="Surrounding text snippet highlighting match location")


class ArchiveSearchResponse(BaseModel):
    """Consolidated response delivered to the inquiring agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(description="Original search query string")
    total_matched: int = Field(ge=0, description="Total records matching criteria before limit")
    items: list[ArchiveSearchResultItem] = Field(default_factory=list, description="Top ranked search result items")
