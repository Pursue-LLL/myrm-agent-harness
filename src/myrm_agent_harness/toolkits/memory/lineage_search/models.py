"""Types and models for lineage search.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SessionSourceKind: Categorical source identifying session provenance and priority.
- ConversationMessage: Individual message unit within a stored conversation session.
- SessionMeta: Session metadata recording provenance and compaction lineage roots.
- RawSearchHit: Unprocessed match output directly from FTS5 lexical matching.
- HydratedSessionHit: Hydrated discovery entry with adaptive window detail and deep link.
- LineageSearchOptions: Options governing discovery search, demotion, and hydration bounds.
- LineageSearchStats: Operational telemetry of lineage search repository.

[POS]
Types and models for lineage search.
"""

# [POS]: myrm_agent_harness/toolkits/memory/lineage_search/models.py
# [INPUT]: Conversation sessions, messages, query options, and hydration configs
# [OUTPUT]: Strongly-typed models for lineage dedup, source demotion, and adaptive hydration

from dataclasses import dataclass, field
from enum import StrEnum


class SessionSourceKind(StrEnum):
    """Categorical source identifying session provenance and priority."""

    INTERACTIVE = "interactive"          # User interactive terminal / chat (highest priority)
    CRON = "cron"                        # Recurring scheduled jobs (demoted in ranking to avoid recall blindness)
    SUBAGENT = "subagent"                # Delegate subagent worker (hidden by default)
    KANBAN = "kanban"                    # Async workflow / queue processor (hidden by default)
    INTERNAL_WORKER = "internal_worker"  # Background housekeeping worker (hidden by default)


@dataclass(slots=True)
class ConversationMessage:
    """Individual message unit within a stored conversation session."""

    message_id: str
    session_id: str
    role: str                            # e.g., "user", "assistant", "system", "tool"
    content: str
    created_at: str
    sequence_num: int = 0


@dataclass(slots=True)
class SessionMeta:
    """Session metadata recording provenance and compaction lineage roots."""

    session_id: str
    title: str = ""
    source: SessionSourceKind = SessionSourceKind.INTERACTIVE
    lineage_root_id: str = ""            # Root identifier shared across compaction lineage generations
    parent_session_id: str = ""
    model: str = ""
    started_at: str = ""

    def effective_lineage_root(self) -> str:
        """Derive the canonical lineage root session ID."""
        return self.lineage_root_id or self.session_id


@dataclass(slots=True)
class RawSearchHit:
    """Unprocessed match output directly from FTS5 lexical matching."""

    session_id: str
    message_id: str
    role: str
    content_snippet: str
    score: float
    source: SessionSourceKind = SessionSourceKind.INTERACTIVE


@dataclass(slots=True)
class HydratedSessionHit:
    """Hydrated discovery entry with adaptive window detail and deep link."""

    session_id: str
    lineage_root_id: str
    title: str
    source: str
    score: float
    match_message_id: str
    snippet: str
    detail_level: str                    # "full" (Top 1) or "compact" (Top 2-N)
    deep_link: str                       # e.g., "@session:{session_id}#msg_{match_message_id}"
    window_messages: list[ConversationMessage] = field(default_factory=list)
    bookend_start: list[ConversationMessage] = field(default_factory=list)
    bookend_end: list[ConversationMessage] = field(default_factory=list)
    messages_before: int = 0
    messages_after: int = 0


@dataclass(slots=True)
class LineageSearchOptions:
    """Options governing discovery search, demotion, and hydration bounds."""

    query: str
    limit: int = 10
    max_scan_limit: int = 300            # Over-scan limit before demotion pass
    include_hidden: bool = False         # True to include subagent/kanban workers
    anchor_window: int = 5               # Messages before/after the matched anchor
    bookend_count: int = 3               # Head/tail messages retained for full detail


@dataclass(slots=True)
class LineageSearchStats:
    """Operational telemetry of lineage search repository."""

    total_sessions: int
    total_messages: int
    hidden_sources_count: int
    demoted_sources_count: int
