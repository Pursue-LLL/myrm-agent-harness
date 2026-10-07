"""Strongly typed contracts for Agent Session History FTS5 Search Toolkit.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- SessionSearchScope: Search boundaries (current session vs cross-session).
- SearchRoleFilter: Filter for specific message roles.
- SessionSearchQuery: Input query specification supporting full-text, filters, and limits.
- SessionSearchHit: Single matched dialogue fragment with highlight snippet and citations.
- SessionSearchResult: Aggregated search output with total count, hits, and latency metrics.

[POS]
Defines data structures powering in-process SQLite FTS5 search,
verbatim message retrieval, and factual attribution across historical dialogues.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class SessionSearchScope(str, enum.Enum):
    """Scope boundary for historical search."""

    CURRENT_SESSION = "current"
    CROSS_SESSION_ALL = "all"


class SearchRoleFilter(str, enum.Enum):
    """Message role filter for search queries."""

    ALL = "all"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class SessionSearchQuery:
    """Query parameters for historical conversation retrieval."""

    query: str
    session_id: str
    scope: SessionSearchScope = SessionSearchScope.CURRENT_SESSION
    role: SearchRoleFilter = SearchRoleFilter.ALL
    turn_min: int | None = None
    turn_max: int | None = None
    limit: int = 10
    include_full_output: bool = False


@dataclass(slots=True)
class SessionSearchHit:
    """Individual match hit returned by FTS5 search engine."""

    message_id: str
    session_id: str
    turn_index: int
    role: str
    tool_name: str | None
    snippet: str
    full_content: str | None
    relevance_score: float
    citation_tag: str

    def to_dict(self) -> dict[str, object]:
        """Serializes search hit to a JSON-compatible dictionary."""
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "role": self.role,
            "tool_name": self.tool_name,
            "snippet": self.snippet,
            "full_content": self.full_content,
            "relevance_score": self.relevance_score,
            "citation_tag": self.citation_tag,
        }


@dataclass(slots=True)
class SessionSearchResult:
    """Aggregated outcome of historical session search."""

    query: str
    total_hits: int
    hits: list[SessionSearchHit] = field(default_factory=list)
    search_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes result into dictionary."""
        return {
            "query": self.query,
            "total_hits": self.total_hits,
            "hits": [h.to_dict() for h in self.hits],
            "search_duration_ms": self.search_duration_ms,
        }
