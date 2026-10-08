"""Decoupled digest synthesizer for distilling turns tagged with SUMMARIZE fate into structured context.

[INPUT]
- TurnEvidence: Sequence of turns destined for summarization.
- TriFateCompactionConfig: Configuration containing token budgets and window limits.

[OUTPUT]
- DecoupledDigestSynthesizer: Produces compact, faithful summaries without touching kept or dropped turns.

[POS]
Decoupled synthesis conduit in compaction pipeline generating summaries exclusively for SUMMARIZE partition.
"""

from __future__ import annotations

from typing import Sequence

from .tri_fate_types import TriFateCompactionConfig, TurnEvidence


class DecoupledDigestSynthesizer:
    """Transforms turns partitioned under SUMMARIZE fate into tight, chronologically grounded digests."""

    def __init__(self, config: TriFateCompactionConfig | None = None) -> None:
        self._config = config or TriFateCompactionConfig()

    def _distill_single_turn(self, turn: TurnEvidence, max_chars: int = 180) -> str:
        """Distill the core statement of a turn without redundant phrasing."""
        lines = [line.strip() for line in turn.content.splitlines() if line.strip()]
        if not lines:
            return ""

        # Take the most salient leading and trailing essence
        joined = " ".join(lines)
        if len(joined) <= max_chars:
            return joined
        return joined[:max_chars].rstrip() + "..."

    def synthesize_digest(self, turns: Sequence[TurnEvidence]) -> str:
        """Generate a structured Markdown digest for all turns assigned the SUMMARIZE fate.

        Produces a chronological list of compressed key takeaways while preserving turn provenance.
        """
        if not turns:
            return ""

        first_turn_id = turns[0].turn_id
        last_turn_id = turns[-1].turn_id

        digest_lines: list[str] = [
            f"### [Compacted Context Digest: Turns {first_turn_id} to {last_turn_id}]",
        ]

        for turn in turns:
            gist = self._distill_single_turn(turn)
            if gist:
                digest_lines.append(f"- **{turn.role.capitalize()}**: {gist}")

        raw_digest = "\n".join(digest_lines)
        return raw_digest.strip()
