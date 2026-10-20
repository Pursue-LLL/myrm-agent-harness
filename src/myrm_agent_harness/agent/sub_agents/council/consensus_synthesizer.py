"""Confidence-weighted Consensus Synthesizer for multi-model deliberation (Item 65).

[INPUT]
- CouncilProposal list, CritiqueItem list, topic string.

[OUTPUT]
- ConsensusVerdict with synthesized arbitration, confidence rating, and dissenting opinions.

[POS]
- Harness orchestration layer for arbitrating multi-model deliberation outputs.
"""

from __future__ import annotations

import uuid

from myrm_agent_harness.agent.sub_agents.council.types import (
    ConsensusVerdict,
    CouncilProposal,
    CritiqueItem,
    CritiqueSeverity,
)

SEVERITY_PENALTY: dict[CritiqueSeverity, float] = {
    CritiqueSeverity.LOW: 0.02,
    CritiqueSeverity.MEDIUM: 0.05,
    CritiqueSeverity.HIGH: 0.12,
    CritiqueSeverity.BLOCKER: 0.25,
}


class ConsensusSynthesizer:
    """Arbitrates heterogeneous model outputs through confidence weighting and critique penalties."""

    @classmethod
    def synthesize(
        cls,
        topic: str,
        proposals: list[CouncilProposal],
        critiques: list[CritiqueItem],
    ) -> ConsensusVerdict:
        """Synthesize a unified consensus verdict across participating proposals and critiques."""
        verdict_id = f"verdict_{uuid.uuid4().hex[:8]}"
        if not proposals:
            return ConsensusVerdict(
                verdict_id=verdict_id,
                final_decision=f"No consensus reached on '{topic}': zero proposals submitted.",
                confidence_rating=0.0,
                key_tradeoffs=["Insufficient deliberation data."],
                participating_models=[],
                dissenting_opinions=[],
            )

        participating_models = sorted({p.model_name for p in proposals})

        # Calculate penalized score per proposal based on unrefuted or critical critiques
        proposal_scores: dict[str, float] = {}
        critique_map: dict[str, list[CritiqueItem]] = {p.proposal_id: [] for p in proposals}
        for c in critiques:
            if c.target_proposal_id in critique_map:
                critique_map[c.target_proposal_id].append(c)

        for p in proposals:
            score = p.confidence_score
            for c in critique_map.get(p.proposal_id, []):
                # If rebuttal provided, penalty is halved
                penalty = SEVERITY_PENALTY.get(c.severity, 0.05)
                if c.defense_rebuttal:
                    penalty *= 0.5
                score -= penalty
            proposal_scores[p.proposal_id] = max(0.1, round(score, 3))

        # Rank proposals
        ranked_proposals = sorted(
            proposals,
            key=lambda item: proposal_scores.get(item.proposal_id, 0.0),
            reverse=True,
        )
        winning_proposal = ranked_proposals[0]
        avg_confidence = round(
            sum(proposal_scores.values()) / len(proposal_scores),
            2,
        )

        # Synthesize tradeoffs and dissenting opinions
        key_tradeoffs: list[str] = [
            f"Adopted primary strategy '{winning_proposal.title}' (Model: {winning_proposal.model_name}).",
        ]
        for arg in winning_proposal.key_arguments[:2]:
            key_tradeoffs.append(f"Core pillar: {arg}")

        dissenting_opinions: list[str] = []
        for p in ranked_proposals[1:]:
            if proposal_scores.get(p.proposal_id, 0.0) >= 0.5:
                dissenting_opinions.append(
                    f"Alternative by {p.model_name}: {p.title} (Confidence: {proposal_scores.get(p.proposal_id):.2f})"
                )

        final_decision = (
            f"Consensus approved for '{topic}': {winning_proposal.title}. "
            f"Synthesized across {len(proposals)} base models with aggregated confidence of {avg_confidence:.2f}."
        )

        return ConsensusVerdict(
            verdict_id=verdict_id,
            final_decision=final_decision,
            confidence_rating=avg_confidence,
            key_tradeoffs=key_tradeoffs,
            participating_models=participating_models,
            dissenting_opinions=dissenting_opinions,
        )
