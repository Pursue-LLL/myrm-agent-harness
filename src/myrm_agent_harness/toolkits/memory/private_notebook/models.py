"""[POS]: src/myrm_agent_harness/toolkits/memory/private_notebook/models.py
[INPUT]: Note attributes, history context items, and new context switching directives.
[OUTPUT]: Immutable Pydantic models for private notes, search hits, history contexts, and switch results.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class NoteMetadata(BaseModel):
    """Metadata summary of a single model private note entry."""

    title: str = Field(description="Unique title and filename of the note without extension")
    char_count: int = Field(ge=0, description="Total character length of the note content")
    line_count: int = Field(ge=0, description="Total line count of the note content")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last update or modification",
    )
    tags: list[str] = Field(default_factory=list, description="Categorical tags attached to the note")


class NoteEntry(BaseModel):
    """Full content of a model private note entry."""

    title: str = Field(description="Unique title of the note")
    content: str = Field(description="Markdown body content written by the model or human")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last update",
    )
    tags: list[str] = Field(default_factory=list, description="Categorical tags")


class NoteSearchResult(BaseModel):
    """Hit outcome when searching notes by keywords or semantic cues."""

    title: str = Field(description="Matched note title")
    score: float = Field(ge=0.0, le=1.0, description="Match score or relevance")
    snippet: str = Field(description="Matched snippet or surrounding context excerpt")


class HistoryContextItem(BaseModel):
    """Metadata representing an archived previous conversation context window."""

    context_id: str = Field(description="Identifier of the historical context session")
    title: str = Field(description="Human or model readable context topic title")
    turn_count: int = Field(ge=0, description="Number of conversation turns in this context")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when the context was opened",
    )


class HistoryEntryItem(BaseModel):
    """Single archived entry or message within a historical context window."""

    context_id: str = Field(description="Context window identifier")
    turn_index: int = Field(ge=0, description="Chronological turn index within the context")
    role: str = Field(description="Author role: user, assistant, system, or tool")
    content: str = Field(description="Textual content or command snippet")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of the turn entry",
    )


class NewContextResult(BaseModel):
    """Outcome report when smoothly rotating to a fresh context window."""

    new_context_id: str = Field(description="Newly assigned clean context identifier")
    previous_context_id: str = Field(description="Archived previous context identifier")
    carried_notes_count: int = Field(ge=0, description="Count of active notes available in new context")
    status: str = Field(default="ready", description="Operational status of the clean context")
