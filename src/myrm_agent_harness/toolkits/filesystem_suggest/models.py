"""
[INPUT]
pydantic::BaseModel (POS: DTO validation model)

[OUTPUT]
WorkspaceSuggestionOptions and WorkspacePathSuggestion DTOs.

[POS]
Workspace suggestion contract module. Defines typed options and root-relative result records for consumers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WorkspaceSuggestionKind = Literal["file", "directory"]
WorkspaceSuggestionScope = Literal["workspace"]
WorkspaceScoreTier = Literal["exact", "prefix", "word", "substring", "subsequence", "path"]


class WorkspaceSuggestionOptions(BaseModel):
    """Options for local workspace path suggestions."""

    limit: int = Field(default=30, ge=1, le=100)
    kind: WorkspaceSuggestionKind | Literal["any"] = "file"
    include_hidden: bool = False


class WorkspacePathSuggestion(BaseModel):
    """A path suggestion relative to a workspace root."""

    source: WorkspaceSuggestionScope = "workspace"
    kind: WorkspaceSuggestionKind
    relative_path: str
    basename: str
    directory: str
    score_tier: WorkspaceScoreTier
    score: int
    match_ranges: list[tuple[int, int]] = Field(default_factory=list)
    size: int | None = None
