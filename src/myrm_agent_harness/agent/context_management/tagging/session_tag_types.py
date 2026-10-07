# ============================================================================
# Session Hierarchical Tagging & Metadata Filter Types (Item 156)
# Strict typed contracts for session tags, multi-dimensional queries,
# semantic auto-classification suggestions, and aggregation distribution.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class TagCategory(StrEnum):
    """Categorical classification of session tags."""

    TASK_TYPE = "task_type"  # e.g. #BugFix, #Refactor, #Testing
    PROJECT_TOPIC = "project_topic"  # e.g. #Auth, #Billing, #Database
    SYSTEM_ROLE = "system_role"  # e.g. #Architect, #Reviewer
    CUSTOM = "custom"


class TagColor(StrEnum):
    """Visual palette color codes for tag pills in UI."""

    BLUE = "blue"
    GREEN = "green"
    PURPLE = "purple"
    AMBER = "amber"
    RED = "red"
    GRAY = "gray"


class TagMatchMode(StrEnum):
    """Boolean aggregation logic when filtering across multiple tags."""

    ANY = "any"  # Union (OR)
    ALL = "all"  # Intersection (AND)
    EXACT = "exact"  # Exact set equality


@dataclass(slots=True, frozen=True)
class SessionTag:
    """Strongly-typed metadata tag attached to conversation sessions."""

    tag_id: str
    name: str
    color: TagColor = TagColor.BLUE
    category: TagCategory = TagCategory.CUSTOM
    description: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serializes session tag to dictionary."""
        return {
            "tag_id": self.tag_id,
            "name": self.name,
            "color": str(self.color),
            "category": str(self.category),
            "description": self.description,
        }


@dataclass(slots=True)
class SessionFilterQuery:
    """Multi-dimensional search query across tags, projects, dates, and keywords."""

    tags: tuple[str, ...] = field(default_factory=tuple)
    match_mode: TagMatchMode = TagMatchMode.ANY
    project_id: str | None = None
    is_pinned: bool | None = None
    keyword: str | None = None
    created_after: float | None = None
    created_before: float | None = None

    def to_dict(self) -> dict[str, str | bool | float | None | list[str]]:
        """Serializes filter query to dictionary."""
        return {
            "tags": list(self.tags),
            "match_mode": str(self.match_mode),
            "project_id": self.project_id,
            "is_pinned": self.is_pinned,
            "keyword": self.keyword,
            "created_after": self.created_after,
            "created_before": self.created_before,
        }


@dataclass(slots=True)
class TaggedSessionItem:
    """Session representation with attached tags for metadata filtering."""

    session_id: str
    title: str
    tags: tuple[SessionTag, ...] = field(default_factory=tuple)
    project_id: str | None = None
    is_pinned: bool = False
    message_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def get_tag_names(self) -> set[str]:
        """Returns normalized set of tag names for rapid matching."""
        return {t.name.lower() for t in self.tags}

    def to_dict(self) -> dict[str, str | bool | int | float | None | list[dict[str, str]]]:
        """Serializes tagged session item to dictionary."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "tags": [t.to_dict() for t in self.tags],
            "project_id": self.project_id,
            "is_pinned": self.is_pinned,
            "message_count": self.message_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class AutoTagSuggestion:
    """Autonomous tag recommendation derived from conversation transcript semantics."""

    tag_name: str
    confidence: float
    category: TagCategory
    reasoning: str

    def to_dict(self) -> dict[str, str | float]:
        """Serializes suggestion to dictionary."""
        return {
            "tag_name": self.tag_name,
            "confidence": self.confidence,
            "category": str(self.category),
            "reasoning": self.reasoning,
        }


@dataclass(slots=True)
class TagDistribution:
    """Aggregate analytics on tag popularity across all workspace sessions."""

    tag_counts: dict[str, int] = field(default_factory=dict)
    total_tagged_sessions: int = 0

    def to_dict(self) -> dict[str, int | dict[str, int]]:
        """Serializes tag distribution to dictionary."""
        return {
            "tag_counts": dict(self.tag_counts),
            "total_tagged_sessions": self.total_tagged_sessions,
        }
