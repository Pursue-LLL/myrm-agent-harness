"""Turn-level tri-fate compaction and decoupled digest synthesizer package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- CompactedTurnPartition: Partitioned collections of turns segregated by fate (kept, summarized, dropped).
- DecoupledDigestSynthesizer: Produces compact summaries exclusively for summarized partition.
- TriFateCompactionConfig: Configuration governing confidence gates, batch sizes, and tail preservation.
- TriFateDecisionMarker: Fast classification engine enforcing irreversible drop safety thresholds.
- TurnEvidence: Immutable representation of a conversational turn.
- TurnFate: Three-state destiny enumeration (KEEP, SUMMARIZE, DROP).
- TurnFateDecision: Decision outcome for a turn including fate, confidence, and escalation flag.
- TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite: Primary unified facade for Item 309.
- TurnLevelTriFateCompactionSuite: Short-hand alias for developer convenience.
- TurnLevelTriFateCompactor: High-speed compaction orchestrator producing compacted partitions.

[POS]
Package entry point for tri-fate compaction and safe irreversible drop gating.
"""

from .decoupled_digest_synthesizer import DecoupledDigestSynthesizer
from .tri_fate_decision_marker import TriFateDecisionMarker
from .tri_fate_types import (
    CompactedTurnPartition,
    TriFateCompactionConfig,
    TurnEvidence,
    TurnFate,
    TurnFateDecision,
)
from .turn_level_tri_fate_compaction_suite import (
    TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite,
    TurnLevelTriFateCompactionSuite,
)
from .turn_level_tri_fate_compactor import TurnLevelTriFateCompactor

__all__ = [
    "CompactedTurnPartition",
    "DecoupledDigestSynthesizer",
    "TriFateCompactionConfig",
    "TriFateDecisionMarker",
    "TurnEvidence",
    "TurnFate",
    "TurnFateDecision",
    "TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite",
    "TurnLevelTriFateCompactionSuite",
    "TurnLevelTriFateCompactor",
]
