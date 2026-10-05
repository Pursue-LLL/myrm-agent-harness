"""Anti-Semantic-Aliasing negative contrastive discriminator.

Defends against latent space concept mixing across disparate workspaces and contexts
by enforcing orthogonal metadata verification (inspired by Metis / arXiv:2607.26760).

[INPUT]
- myrm_agent_harness.toolkits.memory.governor.models::* (POS: schemas, anchors, decisions)
- os.path, datetime (POS: path normalization and temporal calculation)

[OUTPUT]
- AntiSemanticAliasingDiscriminator: Core discriminator evaluating recall candidates.

[POS]
Orthogonal verification gate preventing cross-domain memory leakage and semantic aliasing.
"""

from __future__ import annotations

import logging
import os
from typing import Final

from myrm_agent_harness.toolkits.memory.governor.models import (
    AliasingDecision,
    DiscriminatedCandidate,
    GovernedMemoryEntry,
    MemorySourceAnchor,
)

logger = logging.getLogger(__name__)

_DEFAULT_MIN_ACCEPT_SCORE: Final[float] = 0.35


def _is_same_or_child_workspace(target_ws: str, query_ws: str) -> bool:
    """Check if target workspace is identical to or within query workspace."""
    if not target_ws or not query_ws:
        return True
    norm_target = os.path.normpath(target_ws)
    norm_query = os.path.normpath(query_ws)
    if norm_target == norm_query:
        return True
    try:
        common = os.path.commonpath([norm_target, norm_query])
        return common in (norm_target, norm_query)
    except ValueError:
        return False


class AntiSemanticAliasingDiscriminator:
    """Evaluates recall candidates with orthogonal negative contrastive verification."""

    def __init__(self, min_accept_score: float = _DEFAULT_MIN_ACCEPT_SCORE) -> None:
        self.min_accept_score = min_accept_score

    def evaluate(
        self,
        candidate: GovernedMemoryEntry,
        raw_score: float,
        query_anchor: MemorySourceAnchor,
    ) -> DiscriminatedCandidate:
        """Evaluate a single recall candidate against query context to prevent semantic aliasing."""
        cand_anchor = candidate.anchor

        # 1. Hard Check: Workspace Boundary Isolation
        if (
            cand_anchor.workspace_root
            and query_anchor.workspace_root
            and not _is_same_or_child_workspace(cand_anchor.workspace_root, query_anchor.workspace_root)
        ):
            return DiscriminatedCandidate(
                entry=candidate,
                raw_score=raw_score,
                calibrated_score=0.0,
                decision=AliasingDecision.REJECT_CROSS_DOMAIN,
                reason=(
                    f"Cross-workspace aliasing detected: candidate belongs to '{cand_anchor.workspace_root}', "
                    f"active query is in '{query_anchor.workspace_root}'"
                ),
            )

        # 2. Hard Check: Incompatible Actor Conflict
        if cand_anchor.actor_role == "untrusted" and query_anchor.actor_role == "system":
            return DiscriminatedCandidate(
                entry=candidate,
                raw_score=raw_score,
                calibrated_score=0.0,
                decision=AliasingDecision.REJECT_ACTOR_CONFLICT,
                reason="Actor role conflict: untrusted candidate memory rejected for system query",
            )

        # 3. Soft Calibration: Session Proximity and Confidence
        calibrated = raw_score * candidate.confidence

        # If from a different session within the same workspace, apply mild isolation discount
        if (
            cand_anchor.session_id
            and query_anchor.session_id
            and cand_anchor.session_id != query_anchor.session_id
        ):
            calibrated *= 0.85
            decision = AliasingDecision.ISOLATED
            reason = "Same workspace, historical session memory (mildly discounted)"
        else:
            decision = AliasingDecision.ACCEPT
            reason = "Orthogonal source verification passed"

        calibrated = round(min(1.0, max(0.0, calibrated)), 4)

        return DiscriminatedCandidate(
            entry=candidate,
            raw_score=raw_score,
            calibrated_score=calibrated,
            decision=decision,
            reason=reason,
        )

    def filter_batch(
        self,
        candidates: list[tuple[GovernedMemoryEntry, float]],
        query_anchor: MemorySourceAnchor,
    ) -> list[DiscriminatedCandidate]:
        """Discriminate and filter a batch of recall candidates, sorting by calibrated score."""
        results: list[DiscriminatedCandidate] = []
        for entry, score in candidates:
            discriminated = self.evaluate(entry, score, query_anchor)
            if (
                discriminated.decision in (AliasingDecision.ACCEPT, AliasingDecision.ISOLATED)
                and discriminated.calibrated_score >= self.min_accept_score
            ):
                results.append(discriminated)
            else:
                logger.debug(
                    "Blocked candidate %s (%s): %s",
                    entry.entry_id,
                    discriminated.decision,
                    discriminated.reason,
                )

        results.sort(key=lambda d: d.calibrated_score, reverse=True)
        return results
