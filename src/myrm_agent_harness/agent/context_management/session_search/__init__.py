"""Agent Session History FTS5 Search Toolkit (Item 208).

Provides SQLite FTS5-backed full-text search across dialogue history,
verbatim message content recovery, and source citation attribution.

[INPUT]
- agent.context_management.session_search.session_fts5_search_engine::SessionHistoryFTS5SearchEngine (POS:
  Core engine for Agent Session History FTS5 Search Toolkit.)
- agent.context_management.session_search.session_search_types::SearchRoleFilter, SessionSearchHit,
  SessionSearchQuery, SessionSearchResult, SessionSearchScope (POS: Strongly typed contracts for Agent Session
  History FTS5 Search Toolkit.)

[OUTPUT]
- Re-exports: SearchRoleFilter, SessionHistoryFTS5SearchEngine, SessionSearchHit, SessionSearchQuery,
  SessionSearchResult, SessionSearchScope

[POS]
Agent Session History FTS5 Search Toolkit (Item 208).
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.session_search.session_fts5_search_engine import (
    SessionHistoryFTS5SearchEngine,
)
from myrm_agent_harness.agent.context_management.session_search.session_search_types import (
    SearchRoleFilter,
    SessionSearchHit,
    SessionSearchQuery,
    SessionSearchResult,
    SessionSearchScope,
)

__all__ = [
    "SearchRoleFilter",
    "SessionHistoryFTS5SearchEngine",
    "SessionSearchHit",
    "SessionSearchQuery",
    "SessionSearchResult",
    "SessionSearchScope",
]
