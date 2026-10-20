"""[INPUT] None.
[OUTPUT] Enum types and data contracts for Hierarchical Leader-Worker Debate & Synthesis Pattern.
[POS] Subagent debate synthesis pattern domain types.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class SynthesisPhase(StrEnum):
    """Lifecycle phase of the hierarchical debate synthesis workflow."""

    INITIALIZING = "initializing"
    DECOMPOSITION = "decomposition"
    RESEARCH_DISCOVERY = "research_discovery"
    FEASIBILITY_CRITIQUE = "feasibility_critique"
    CROSS_DEBATE = "cross_debate"
    SYNTHESIS_CONVERGENCE = "synthesis_convergence"
    COMPLETED = "completed"


class SynthesisRole(StrEnum):
    """Preset specialist roles in the three-stage hierarchical consulting pattern."""

    LEADER_COORDINATOR = "leader_coordinator"
    RESEARCH_ANALYST = "research_analyst"
    FEASIBILITY_AUDITOR = "feasibility_auditor"


class TradeoffDimension(StrEnum):
    """Standard comparison dimensions evaluated in the trade-off matrix."""

    PERFORMANCE = "performance"
    COST_EFFICIENCY = "cost_efficiency"
    IMPLEMENTATION_COMPLEXITY = "implementation_complexity"
    RELIABILITY = "reliability"
    MAINTAINABILITY = "maintainability"


@dataclass
class SynthesisParticipant:
    """Participant in the hierarchical synthesis panel."""

    agent_id: str
    name: str
    role: SynthesisRole
    model: str | None = None


@dataclass
class SynthesisSubtask:
    """Subtask derived by Leader with explicit dependency topological links."""

    task_id: str
    title: str
    assigned_role: SynthesisRole
    assigned_agent_id: str
    description: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "todo"
    output_summary: str | None = None


@dataclass
class CandidateProposal:
    """Candidate solution proposal drafted by an analyst or auditor."""

    proposal_id: str
    title: str
    author_role: SynthesisRole
    author_agent_id: str
    summary: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    dimension_scores: dict[str, float] = field(default_factory=dict)
    is_recommended: bool = False


@dataclass
class TradeoffMatrix:
    """Multidimensional decision trade-off matrix synthesized by the Leader."""

    matrix_id: str
    workflow_id: str
    dimensions: list[str]
    dimension_weights: dict[str, float]
    proposals: list[CandidateProposal]
    winner_proposal_id: str | None
    recommendation_rationale: str
    created_at: float = field(default_factory=time.time)


@dataclass
class SynthesisWorkflowState:
    """Entire state snapshot of a hierarchical debate & synthesis session."""

    workflow_id: str
    chat_id: str
    topic: str
    phase: SynthesisPhase
    participants: list[SynthesisParticipant]
    subtasks: list[SynthesisSubtask] = field(default_factory=list)
    proposals: list[CandidateProposal] = field(default_factory=list)
    matrix: TradeoffMatrix | None = None
    round_index: int = 1
    max_rounds: int = 2
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
