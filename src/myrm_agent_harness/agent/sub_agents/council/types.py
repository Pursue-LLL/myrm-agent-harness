"""Type definitions for Council of Agents Multi-Model Deliberation Protocol (Item 65).

[INPUT]
- Multi-model deliberation requests, blind proposals, cross-critiques, and rebuttal arguments.

[OUTPUT]
- CouncilProposal, CritiqueItem, ConsensusVerdict, CouncilSession data structures.

[POS]
- Harness orchestration definitions for multi-model council deliberation and arbitration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class DeliberationPhase(StrEnum):
    """Discrete phases of the multi-model council deliberation protocol."""

    BLIND_PROPOSAL = "blind_proposal"
    CROSS_CRITIQUE = "cross_critique"
    REBUTTAL = "rebuttal"
    CONSENSUS_SYNTHESIS = "consensus_synthesis"
    FINALIZED = "finalized"


class CouncilMemberTier(StrEnum):
    """Persona role tiers within the deliberative council."""

    LEAD = "lead"
    SPECIALIST = "specialist"
    SKEPTIC = "skeptic"
    SYNTHESIZER = "synthesizer"


class CritiqueSeverity(StrEnum):
    """Impact severity of a cross-model critique point."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKER = "blocker"


@dataclass(slots=True)
class CouncilProposal:
    """Independent blind proposal drafted by a participating base model."""

    proposal_id: str
    member_id: str
    model_name: str
    title: str
    reasoning_steps: list[str] = field(default_factory=list)
    key_arguments: list[str] = field(default_factory=list)
    confidence_score: float = 0.85


@dataclass(slots=True)
class CritiqueItem:
    """Anonymous cross-model critique targeting a specific proposal."""

    critique_id: str
    source_member_id: str
    target_member_id: str
    target_proposal_id: str
    critique_points: list[str] = field(default_factory=list)
    severity: CritiqueSeverity = CritiqueSeverity.MEDIUM
    defense_rebuttal: str | None = None


@dataclass(slots=True)
class ConsensusVerdict:
    """Synthesized council consensus verdict with weighted arbitration."""

    verdict_id: str
    final_decision: str
    confidence_rating: float
    key_tradeoffs: list[str] = field(default_factory=list)
    participating_models: list[str] = field(default_factory=list)
    dissenting_opinions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CouncilSession:
    """End-to-end deliberation state container for a council session."""

    session_id: str
    deliberation_topic: str
    phase: DeliberationPhase = DeliberationPhase.BLIND_PROPOSAL
    proposals: dict[str, CouncilProposal] = field(default_factory=dict)
    critiques: list[CritiqueItem] = field(default_factory=list)
    consensus: ConsensusVerdict | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
