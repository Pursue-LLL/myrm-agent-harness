"""Turn-level tri-fate decision marker arbitrating keep/summarize/drop destinies with safety gating.

[INPUT]
- TurnEvidence: Conversational turn snapshot.
- TriFateCompactionConfig: Configuration containing confidence thresholds and tail preservation counts.
- TurnFate, TurnFateDecision: Outcome models.

[OUTPUT]
- TriFateDecisionMarker: Fast classification engine enforcing irreversible drop safety thresholds.

[POS]
Frontline micro-decision layer in compaction pipeline evaluating turn survivability prior to synthesis.
"""

from __future__ import annotations

import re
from typing import Sequence

from .tri_fate_types import (
    TriFateCompactionConfig,
    TurnEvidence,
    TurnFate,
    TurnFateDecision,
)


class TriFateDecisionMarker:
    """Evaluates conversation turns and assigns tripartite fates with strict drop confidence gating."""

    # Heuristic patterns identifying technical anchors that mandate exact preservation
    TECHNICAL_ANCHOR_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b)", re.IGNORECASE),
        re.compile(r"(\b(?:https?://|file:///)[^\s]+)"),
        re.compile(r"([a-zA-Z0-9_\-\./]+\.(?:py|ts|tsx|js|json|md|rs|go|sh|toml|yaml|yml)(?::\d+)?)"),
        re.compile(r"(Traceback \(most recent call last\):|\b(?:Error|Exception|Failed|assert)\b)", re.IGNORECASE),
        re.compile(r"(\b(?:git|pytest|cargo|docker|npm|bun|pip|curl)\s+[a-z0-9_\-\./]+)", re.IGNORECASE),
        re.compile(r"(- \[[ x]\]\s+.+)"),
        re.compile(r"(必须|严禁|绝不|always|never|mandatory|do not)\b", re.IGNORECASE),
    )

    # Patterns matching pure transient chatter, acknowledgements, or ephemeral confirmations
    CHATTER_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^(ok|okay|got it|sure|thanks|thank you|sounds good|understood)[.!]?$", re.IGNORECASE),
        re.compile(r"^(好的|收到|明白了|行|可以|知道了|没问题)[。！]?", re.IGNORECASE),
        re.compile(r"^(i will proceed|starting work now|continuing|acknowledged)[.!]?$", re.IGNORECASE),
    )

    def __init__(self, config: TriFateCompactionConfig | None = None) -> None:
        self._config = config or TriFateCompactionConfig()

    def extract_anchors(self, text: str) -> tuple[str, ...]:
        """Extract explicit architectural, diagnostic, and task anchors requiring exact recall."""
        if not self._config.extract_technical_anchors:
            return ()

        anchors: list[str] = []
        for pattern in self.TECHNICAL_ANCHOR_PATTERNS:
            for match in pattern.finditer(text):
                anchor_text = match.group(1).strip()
                if anchor_text and anchor_text not in anchors:
                    anchors.append(anchor_text)
                    if len(anchors) >= 8:
                        return tuple(anchors)
        return tuple(anchors)

    def _inspect_head_tail(self, text: str) -> str:
        """Inspect the head and tail window of a turn for fast decision-making."""
        trimmed = text.strip()
        win = self._config.head_tail_char_window
        if len(trimmed) <= win * 2:
            return trimmed
        return trimmed[:win] + "\n...[TRUNCATED]...\n" + trimmed[-win:]

    def evaluate_turn(
        self,
        turn: TurnEvidence,
        turn_index: int,
        total_turns: int,
    ) -> TurnFateDecision:
        """Evaluate an individual turn's fate, enforcing drop confidence threshold and tail safety."""
        # 1. Tail preservation guard: recent turns are unconditionally kept
        turns_from_end = total_turns - 1 - turn_index
        if turns_from_end < self._config.preserve_last_n_turns:
            return TurnFateDecision(
                turn_id=turn.turn_id,
                fate=TurnFate.KEEP,
                confidence=1.0,
                rationale="Unconditionally preserved within recent turn tail window",
            )

        window_text = self._inspect_head_tail(turn.content)
        anchors = self.extract_anchors(window_text)

        # 2. Hard Keep: Presence of concrete technical anchors, paths, or strict constraints
        if anchors:
            return TurnFateDecision(
                turn_id=turn.turn_id,
                fate=TurnFate.KEEP,
                confidence=0.95,
                rationale=f"Contains critical technical anchors: {', '.join(anchors[:3])}",
                extracted_anchors=anchors,
            )

        # 3. Check for pure transient chatter candidate
        is_chatter = any(pat.search(turn.content.strip()) for pat in self.CHATTER_PATTERNS)
        if is_chatter:
            candidate_confidence = 0.90
            return TurnFateDecision(
                turn_id=turn.turn_id,
                fate=TurnFate.DROP,
                confidence=candidate_confidence,
                rationale="Transient conversational chatter with zero technical dependency",
            )

        # 4. Long descriptive text or background explanation: default candidate fate
        # If text is extremely short and low informativeness, check drop candidate
        cleaned = turn.content.strip()
        if len(cleaned) < 30 and turn.role == "user" and not anchors:
            # Low-confidence drop candidate: check against confidence gate
            drop_confidence = 0.55
            if drop_confidence < self._config.min_drop_confidence:
                # Escalation safety net: Irreversible drop below threshold is promoted to SUMMARIZE
                return TurnFateDecision(
                    turn_id=turn.turn_id,
                    fate=TurnFate.SUMMARIZE,
                    confidence=0.85,
                    rationale="Short turn with marginal certainty; safely escalated from DROP to SUMMARIZE",
                    was_escalated_from_drop=True,
                )
            return TurnFateDecision(
                turn_id=turn.turn_id,
                fate=TurnFate.DROP,
                confidence=drop_confidence,
                rationale="Short non-informative user confirmation",
            )

        # 5. Default fate for informative context: SUMMARIZE
        return TurnFateDecision(
            turn_id=turn.turn_id,
            fate=TurnFate.SUMMARIZE,
            confidence=0.85,
            rationale="Informative contextual progression and background reasoning",
        )

    def evaluate_batch(self, turns: Sequence[TurnEvidence]) -> Sequence[TurnFateDecision]:
        """Arbitrate fates for a batch of turns sequentially."""
        total = len(turns)
        return tuple(
            self.evaluate_turn(turn=t, turn_index=idx, total_turns=total)
            for idx, t in enumerate(turns)
        )
