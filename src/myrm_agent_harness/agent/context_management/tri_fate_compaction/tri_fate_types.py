# [INPUT]: None
# [OUTPUT]: CompactedTurnPartition, TriFateCompactionConfig, TurnEvidence, TurnFate, TurnFateDecision
# [POS]: agent/context_management/tri_fate_compaction/tri_fate_types.py

"""Domain models and contracts for turn-level tri-fate compaction and decoupled digest synthesis.

[INPUT]
- None (Self-contained domain models and contracts).

[OUTPUT]
- TurnFate: Three-state destiny enumeration (KEEP, SUMMARIZE, DROP).
- TurnEvidence: Represents a conversation turn with role, content, and token telemetry.
- TurnFateDecision: Decision outcome for a turn including fate, confidence, rationale, and escalation flag.
- CompactedTurnPartition: Partitioned collections of turns segregated by fate (kept, summarized, dropped).
- TriFateCompactionConfig: Configuration governing confidence gates, batch sizes, and tail preservation.

[POS]
Domain contract layer for turn-level tri-fate compaction and safe irreversible drop gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class TurnFate(str, Enum):
    """The three discrete destinies for conversation turns during compaction."""

    KEEP = "keep"
    SUMMARIZE = "summarize"
    DROP = "drop"


@dataclass(frozen=True)
class TurnEvidence:
    """Immutable representation of a conversational turn subjected to fate arbitration."""

    turn_id: str
    role: str
    content: str
    token_count: int = 0
    timestamp: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnFateDecision:
    """Authoritative fate judgment for an individual conversational turn."""

    turn_id: str
    fate: TurnFate
    confidence: float
    rationale: str
    was_escalated_from_drop: bool = False
    extracted_anchors: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompactedTurnPartition:
    """Disjoint partition of conversation turns segregated by their assigned fate."""

    kept_turns: Sequence[TurnEvidence] = field(default_factory=tuple)
    summarized_turns: Sequence[TurnEvidence] = field(default_factory=tuple)
    dropped_turns: Sequence[TurnEvidence] = field(default_factory=tuple)

    @property
    def total_turns(self) -> int:
        """Total number of turns across all partitions."""
        return len(self.kept_turns) + len(self.summarized_turns) + len(self.dropped_turns)

    @property
    def drop_ratio(self) -> float:
        """Proportion of turns successfully dropped to relieve context pressure."""
        if self.total_turns == 0:
            return 0.0
        return len(self.dropped_turns) / self.total_turns


@dataclass(frozen=True)
class TriFateCompactionConfig:
    """Configuration governing tri-fate decision thresholds and compaction policies."""

    min_drop_confidence: float = 0.7
    batch_size: int = 40
    head_tail_char_window: int = 350
    preserve_last_n_turns: int = 4
    max_summary_tokens: int = 600
    extract_technical_anchors: bool = True
