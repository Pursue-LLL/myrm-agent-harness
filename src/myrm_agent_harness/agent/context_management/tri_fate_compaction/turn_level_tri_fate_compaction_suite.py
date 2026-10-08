"""Comprehensive facade suite for turn-level tri-fate compaction and decoupled digest synthesis.

[INPUT]
- TurnEvidence: Sequence of conversation turns with role and content.
- TriFateCompactionConfig: Configuration governing confidence gates and batch sizes.
- TriFateDecisionMarker, DecoupledDigestSynthesizer, TurnLevelTriFateCompactor: Underlying engines.

[OUTPUT]
- TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite: Primary unified facade for Item 309.
- TurnLevelTriFateCompactionSuite: Short-hand alias for developer convenience.

[POS]
Main entry point for tri-fate compaction, safety drop gating, and decoupled digest synthesis.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .decoupled_digest_synthesizer import DecoupledDigestSynthesizer
from .tri_fate_decision_marker import TriFateDecisionMarker
from .tri_fate_types import (
    CompactedTurnPartition,
    TriFateCompactionConfig,
    TurnEvidence,
    TurnFate,
    TurnFateDecision,
)
from .turn_level_tri_fate_compactor import TurnLevelTriFateCompactor


class TurnLevelTriFateCompactionSuite:
    """Unified facade managing turn-level tri-fate arbitration, drop safety gates, and decoupled synthesis."""

    def __init__(self, config: TriFateCompactionConfig | None = None) -> None:
        self._config = config or TriFateCompactionConfig()
        self._marker = TriFateDecisionMarker(self._config)
        self._synthesizer = DecoupledDigestSynthesizer(self._config)
        self._compactor = TurnLevelTriFateCompactor(self._config)

    @property
    def config(self) -> TriFateCompactionConfig:
        """The configuration in effect."""
        return self._config

    def evaluate_single_turn(
        self,
        turn: TurnEvidence,
        turn_index: int,
        total_turns: int,
    ) -> TurnFateDecision:
        """Evaluate an individual turn's fate directly via the decision marker."""
        return self._marker.evaluate_turn(turn=turn, turn_index=turn_index, total_turns=total_turns)

    def partition_turns(
        self,
        turns: Sequence[TurnEvidence],
    ) -> tuple[CompactedTurnPartition, Sequence[TurnFateDecision]]:
        """Evaluate a batch of turns and partition them into kept, summarized, and dropped sets."""
        return self._compactor.partition_turns(turns)

    def synthesize_digest(self, turns: Sequence[TurnEvidence]) -> str:
        """Synthesize a chronological Markdown digest exclusively for summarized turns."""
        return self._synthesizer.synthesize_digest(turns)

    def compact_conversation(
        self,
        turns: Sequence[TurnEvidence],
    ) -> tuple[str, CompactedTurnPartition, Mapping[str, object]]:
        """Execute complete end-to-end tri-fate compaction and context reconstruction pipeline."""
        return self._compactor.compact_and_reconstruct(turns)


TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite = TurnLevelTriFateCompactionSuite
