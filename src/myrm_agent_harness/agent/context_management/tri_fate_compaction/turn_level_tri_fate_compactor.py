# [INPUT]: CompactedTurnPartition, DecoupledDigestSynthesizer, TriFateCompactionConfig, TriFateDecisionMarker, TurnEvidence, TurnFate, TurnFateDecision
# [OUTPUT]: TurnLevelTriFateCompactor
# [POS]: agent/context_management/tri_fate_compaction/turn_level_tri_fate_compactor.py

"""Turn-level tri-fate compactor orchestrating tripartite partitioning, decoupled synthesis, and assembly.

[INPUT]
- TurnEvidence: Sequence of conversation turns.
- TriFateCompactionConfig: Configuration governing compaction thresholds.
- TriFateDecisionMarker: Micro-decision engine classifying turn fates.
- DecoupledDigestSynthesizer: Synthesis conduit condensing SUMMARIZE turns.

[OUTPUT]
- TurnLevelTriFateCompactor: High-speed compaction orchestrator producing compacted partitions and reconstituted prompts.

[POS]
Main compaction pipeline coordinating tri-fate division, drop gating, and decoupled digest assembly.
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


class TurnLevelTriFateCompactor:
    """Orchestrates turn-level tripartite fate partitioning and decoupled context reconstruction."""

    def __init__(self, config: TriFateCompactionConfig | None = None) -> None:
        self._config = config or TriFateCompactionConfig()
        self._decision_marker = TriFateDecisionMarker(self._config)
        self._digest_synthesizer = DecoupledDigestSynthesizer(self._config)

    def partition_turns(
        self,
        turns: Sequence[TurnEvidence],
    ) -> tuple[CompactedTurnPartition, Sequence[TurnFateDecision]]:
        """Evaluate turns and partition them into kept, summarized, and dropped collections."""
        decisions = self._decision_marker.evaluate_batch(turns)

        kept: list[TurnEvidence] = []
        summarized: list[TurnEvidence] = []
        dropped: list[TurnEvidence] = []

        decision_by_id: dict[str, TurnFateDecision] = {d.turn_id: d for d in decisions}

        for turn in turns:
            dec = decision_by_id.get(turn.turn_id)
            if dec is None:
                kept.append(turn)
                continue

            match dec.fate:
                case TurnFate.KEEP:
                    kept.append(turn)
                case TurnFate.SUMMARIZE:
                    summarized.append(turn)
                case TurnFate.DROP:
                    dropped.append(turn)

        partition = CompactedTurnPartition(
            kept_turns=tuple(kept),
            summarized_turns=tuple(summarized),
            dropped_turns=tuple(dropped),
        )
        return partition, decisions

    def compact_and_reconstruct(
        self,
        turns: Sequence[TurnEvidence],
    ) -> tuple[str, CompactedTurnPartition, Mapping[str, object]]:
        """Execute full compaction pipeline: partitioning, digest synthesis, and prompt reconstruction.

        Returns:
            A tuple of (reconstructed_context_text, partition, audit_telemetry).
        """
        partition, decisions = self.partition_turns(turns)

        # Synthesize digest for summarized partition only
        digest_text = self._digest_synthesizer.synthesize_digest(partition.summarized_turns)

        # Assemble reconstructed context
        reconstructed_blocks: list[str] = []
        if digest_text:
            reconstructed_blocks.append(digest_text)

        for turn in partition.kept_turns:
            reconstructed_blocks.append(f"[{turn.role.upper()}]: {turn.content.strip()}")

        reconstructed_context = "\n\n".join(reconstructed_blocks).strip()

        # Compile audit telemetry
        escalated_count = sum(1 for d in decisions if d.was_escalated_from_drop)
        audit_telemetry: dict[str, object] = {
            "total_turns": partition.total_turns,
            "kept_count": len(partition.kept_turns),
            "summarized_count": len(partition.summarized_turns),
            "dropped_count": len(partition.dropped_turns),
            "drop_ratio": round(partition.drop_ratio, 4),
            "escalated_from_drop_count": escalated_count,
            "digest_synthesized": bool(digest_text),
        }

        return reconstructed_context, partition, audit_telemetry
