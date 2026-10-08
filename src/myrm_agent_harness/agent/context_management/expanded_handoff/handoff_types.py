"""Domain models and contracts for 1,200-word expanded skeleton anchor and searchable archive handoffs.

[INPUT]
- None (Self-contained domain models and contracts).

[OUTPUT]
- HistoricalSessionTurn: Immutable turn snapshot from prior session history.
- ExpandedHandoffAnchor: 1,200-word expanded dialogue skeleton with origin session pointer.
- ArchiveSearchResult: Reconstructed snippet result from searching old session archives.
- ExpandedHandoffConfig: Configuration governing word budgets, search limits, and thresholds.

[POS]
Domain contract layer for expanded dialogue handoffs with dynamic searchable archive channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class HistoricalSessionTurn:
    """Historical conversation turn recorded from an origin session."""

    turn_id: str
    role: str
    content: str
    timestamp: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExpandedHandoffAnchor:
    """Rich 1,200-word expanded context anchor bridging across conversation sessions."""

    origin_session_id: str
    target_session_id: str
    anchor_title: str
    expanded_skeleton_text: str
    word_count: int
    created_at: float
    origin_total_turns: int
    search_pointer_key: str


@dataclass(frozen=True)
class ArchiveSearchResult:
    """Single matching record retrieved from prior immutable session archives."""

    turn_id: str
    role: str
    matched_snippet: str
    relevance_score: float
    timestamp: float


@dataclass(frozen=True)
class ExpandedHandoffConfig:
    """Configuration governing expanded handoff budgets and search conduit parameters."""

    target_word_budget: int = 1200
    max_char_budget: int = 6500
    search_top_k: int = 3
    min_search_score: float = 0.25
    include_search_conduit_instructions: bool = True
