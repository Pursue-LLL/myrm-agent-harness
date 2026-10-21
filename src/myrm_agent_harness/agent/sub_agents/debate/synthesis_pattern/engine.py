"""[INPUT] types.py.
[OUTPUT] HierarchicalDebateSynthesisEngine: Orchestrator for hierarchical 3-stage leader-worker debate & synthesis.
[POS] Subagent debate synthesis pattern core engine.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import ClassVar

from myrm_agent_harness.agent.sub_agents.debate.synthesis_pattern.types import (
    CandidateProposal,
    SynthesisParticipant,
    SynthesisPhase,
    SynthesisRole,
    SynthesisSubtask,
    SynthesisWorkflowState,
    TradeoffDimension,
    TradeoffMatrix,
)


class HierarchicalDebateSynthesisEngine:
    """Engine orchestrating the three-stage Leader decomposition, specialist debate, and trade-off synthesis."""

    _DEFAULT_DIMENSIONS: ClassVar[list[str]] = [
        TradeoffDimension.PERFORMANCE,
        TradeoffDimension.COST_EFFICIENCY,
        TradeoffDimension.IMPLEMENTATION_COMPLEXITY,
        TradeoffDimension.RELIABILITY,
        TradeoffDimension.MAINTAINABILITY,
    ]

    def __init__(self) -> None:
        self._workflows: dict[str, SynthesisWorkflowState] = {}
        self._lock = threading.Lock()

    def create_workflow(
        self,
        workflow_id: str,
        chat_id: str,
        topic: str,
        leader_id: str,
        researcher_id: str,
        auditor_id: str,
        max_rounds: int = 2,
    ) -> SynthesisWorkflowState:
        """Initialize a standard 3-stage consulting workflow with preset specialist panel."""
        with self._lock:
            participants = [
                SynthesisParticipant(
                    agent_id=leader_id,
                    name="Leader Coordinator",
                    role=SynthesisRole.LEADER_COORDINATOR,
                ),
                SynthesisParticipant(
                    agent_id=researcher_id,
                    name="Research Analyst",
                    role=SynthesisRole.RESEARCH_ANALYST,
                ),
                SynthesisParticipant(
                    agent_id=auditor_id,
                    name="Feasibility Auditor",
                    role=SynthesisRole.FEASIBILITY_AUDITOR,
                ),
            ]

            now = time.time()
            state = SynthesisWorkflowState(
                workflow_id=workflow_id,
                chat_id=chat_id,
                topic=topic,
                phase=SynthesisPhase.DECOMPOSITION,
                participants=participants,
                subtasks=[],
                proposals=[],
                matrix=None,
                round_index=1,
                max_rounds=max_rounds,
                created_at=now,
                updated_at=now,
            )
            self._workflows[workflow_id] = state
            return state

    def get_workflow(self, workflow_id: str) -> SynthesisWorkflowState | None:
        """Fetch workflow state by ID."""
        with self._lock:
            return self._workflows.get(workflow_id)

    def list_workflows(self, chat_id: str) -> list[SynthesisWorkflowState]:
        """List all synthesis workflows for a given chat."""
        with self._lock:
            return [w for w in self._workflows.values() if w.chat_id == chat_id]

    def auto_decompose(
        self,
        workflow_id: str,
        leader_agent_id: str,
        custom_subtasks: list[SynthesisSubtask] | None = None,
    ) -> SynthesisWorkflowState:
        """Leader automatically derives subtask DAG with explicit dependencies."""
        with self._lock:
            state = self._workflows.get(workflow_id)
            if not state:
                raise KeyError(f"Workflow {workflow_id} not found")

            # Verify leader identity
            leader = next(
                (p for p in state.participants if p.agent_id == leader_agent_id and p.role == SynthesisRole.LEADER_COORDINATOR),
                None,
            )
            if not leader:
                raise PermissionError(f"Agent {leader_agent_id} is not the designated Leader Coordinator")

            researcher = next(p for p in state.participants if p.role == SynthesisRole.RESEARCH_ANALYST)
            auditor = next(p for p in state.participants if p.role == SynthesisRole.FEASIBILITY_AUDITOR)

            if custom_subtasks:
                state.subtasks = list(custom_subtasks)
            else:
                task_1_id = f"st-res-{uuid.uuid4().hex[:6]}"
                task_2_id = f"st-aud-{uuid.uuid4().hex[:6]}"

                subtask_1 = SynthesisSubtask(
                    task_id=task_1_id,
                    title=f"Exploratory Research: {state.topic}",
                    assigned_role=SynthesisRole.RESEARCH_ANALYST,
                    assigned_agent_id=researcher.agent_id,
                    description="Investigate cutting-edge implementations, benchmarks, and architectural alternatives.",
                    depends_on=[],
                    status="in_progress",
                )
                subtask_2 = SynthesisSubtask(
                    task_id=task_2_id,
                    title=f"Feasibility & Risk Audit: {state.topic}",
                    assigned_role=SynthesisRole.FEASIBILITY_AUDITOR,
                    assigned_agent_id=auditor.agent_id,
                    description="Critique proposed solutions, quantify operational overhead, security vulnerabilities, and migration cost.",
                    depends_on=[task_1_id],
                    status="todo",
                )
                state.subtasks = [subtask_1, subtask_2]

            state.phase = SynthesisPhase.RESEARCH_DISCOVERY
            state.updated_at = time.time()
            return state

    def submit_proposal(
        self,
        workflow_id: str,
        proposal: CandidateProposal,
    ) -> SynthesisWorkflowState:
        """Submit a candidate proposal authored by an analyst or auditor."""
        with self._lock:
            state = self._workflows.get(workflow_id)
            if not state:
                raise KeyError(f"Workflow {workflow_id} not found")

            state.proposals.append(proposal)

            has_research = any(p.author_role == SynthesisRole.RESEARCH_ANALYST for p in state.proposals)
            has_audit = any(p.author_role == SynthesisRole.FEASIBILITY_AUDITOR for p in state.proposals)

            if has_research and not has_audit:
                state.phase = SynthesisPhase.FEASIBILITY_CRITIQUE
            elif has_research and has_audit:
                state.phase = SynthesisPhase.CROSS_DEBATE

            state.updated_at = time.time()
            return state

    def advance_cross_debate(self, workflow_id: str) -> SynthesisWorkflowState:
        """Progress round in cross-debate, enforcing convergence when max_rounds is met."""
        with self._lock:
            state = self._workflows.get(workflow_id)
            if not state:
                raise KeyError(f"Workflow {workflow_id} not found")

            if state.round_index >= state.max_rounds:
                # Force convergence to synthesis
                state.phase = SynthesisPhase.SYNTHESIS_CONVERGENCE
            else:
                state.round_index += 1
                state.phase = SynthesisPhase.CROSS_DEBATE

            state.updated_at = time.time()
            return state

    def synthesize_decision_matrix(
        self,
        workflow_id: str,
        custom_weights: dict[str, float] | None = None,
        custom_rationale: str | None = None,
    ) -> TradeoffMatrix:
        """Leader compiles multi-dimensional Trade-off Matrix, computing winning proposal and rationale."""
        with self._lock:
            state = self._workflows.get(workflow_id)
            if not state:
                raise KeyError(f"Workflow {workflow_id} not found")

            if not state.proposals:
                raise ValueError("Cannot synthesize decision matrix without candidate proposals")

            # 1. Normalize dimension weights
            raw_weights = custom_weights or {d: 1.0 for d in self._DEFAULT_DIMENSIONS}
            weight_sum = sum(raw_weights.values()) or 1.0
            norm_weights: dict[str, float] = {k: v / weight_sum for k, v in raw_weights.items()}

            # 2. Score proposals across dimensions
            best_score = -1.0
            winner_id: str | None = None

            for proposal in state.proposals:
                composite_score = 0.0
                for dim, weight in norm_weights.items():
                    # Default score is 0.5 if unassessed
                    dim_score = proposal.dimension_scores.get(dim, 0.5)
                    # Bound score within [0.0, 1.0]
                    dim_score = max(0.0, min(1.0, dim_score))
                    composite_score += dim_score * weight

                if composite_score > best_score:
                    best_score = composite_score
                    winner_id = proposal.proposal_id

            # 3. Mark winner proposal
            for proposal in state.proposals:
                proposal.is_recommended = (proposal.proposal_id == winner_id)

            winning_proposal = next((p for p in state.proposals if p.proposal_id == winner_id), None)
            default_rationale = (
                f"Proposal '{winning_proposal.title}' selected as the optimal recommendation "
                f"with balanced score of {best_score:.2f} across {len(norm_weights)} weighted dimensions."
                if winning_proposal
                else "No winning proposal identified."
            )

            matrix = TradeoffMatrix(
                matrix_id=f"matrix-{uuid.uuid4().hex[:8]}",
                workflow_id=workflow_id,
                dimensions=list(norm_weights.keys()),
                dimension_weights=norm_weights,
                proposals=list(state.proposals),
                winner_proposal_id=winner_id,
                recommendation_rationale=custom_rationale or default_rationale,
            )

            state.matrix = matrix
            state.phase = SynthesisPhase.COMPLETED
            state.updated_at = time.time()
            return matrix
