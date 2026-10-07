"""Master suite for DevFlow Context Lifecycle and Progressive Loading.

Coordinates the 4-Question context gate, phase transitions, structured exploration handoffs,
and deferred loading of deliverable templates under strict lifecycle governance.
"""

from __future__ import annotations

from typing import Sequence

from .context_gate_evaluator import ContextGateEvaluator
from .devflow_types import (
    ContextAdmissionDecision,
    DevFlowPhase,
    GateQuestionnaireEvaluation,
    PhaseLifecycleState,
    StructuredExplorationHandoff,
)
from .exploration_handoff_engine import ExplorationHandoffEngine


class DevFlowContextLifecycleAndProgressiveLoadingSuite:
    """Master suite governing phase-driven progressive context loading and transient exploration pruning."""

    def __init__(self) -> None:
        self._gate_evaluator = ContextGateEvaluator()
        self._handoff_engine = ExplorationHandoffEngine()
        self._session_states: dict[str, PhaseLifecycleState] = {}
        self._total_purged_tokens = 0

    @property
    def gate_evaluator(self) -> ContextGateEvaluator:
        """Access underlying 4-Question Gate evaluator."""
        return self._gate_evaluator

    @property
    def handoff_engine(self) -> ExplorationHandoffEngine:
        """Access underlying structured exploration handoff engine."""
        return self._handoff_engine

    def get_or_create_state(self, session_id: str) -> PhaseLifecycleState:
        """Retrieve active lifecycle state or initialize at PLANNING phase."""
        if session_id not in self._session_states:
            self._session_states[session_id] = PhaseLifecycleState(
                session_id=session_id,
                current_phase=DevFlowPhase.PLANNING,
                active_deliverable_templates=[],
                retained_handoffs=[],
                purged_raw_tokens_count=0,
            )
        return self._session_states[session_id]

    def transition_phase(
        self,
        session_id: str,
        target_phase: DevFlowPhase,
        purged_tokens_estimate: int = 0,
    ) -> PhaseLifecycleState:
        """Transition the session into a subsequent phase, purging transient phase tokens."""
        curr = self.get_or_create_state(session_id)
        templates: list[str] = list(curr.active_deliverable_templates)

        # Progressively mount deliverable specifications only in DELIVERY phase
        if target_phase == DevFlowPhase.DELIVERY and "developer-deliverables.md" not in templates:
            templates.append("developer-deliverables.md")
        elif target_phase != DevFlowPhase.DELIVERY:
            templates = [t for t in templates if t != "developer-deliverables.md"]

        new_purged = curr.purged_raw_tokens_count + purged_tokens_estimate
        self._total_purged_tokens += purged_tokens_estimate

        new_state = PhaseLifecycleState(
            session_id=session_id,
            current_phase=target_phase,
            active_deliverable_templates=templates,
            retained_handoffs=list(curr.retained_handoffs),
            purged_raw_tokens_count=new_purged,
        )
        self._session_states[session_id] = new_state
        return new_state

    def evaluate_admission(
        self,
        session_id: str,
        intended_phase: DevFlowPhase,
        content_length: int,
        is_single_use: bool = False,
        has_trigger_condition: bool = False,
        trigger_satisfied: bool = False,
        can_external_lookup: bool = False,
    ) -> GateQuestionnaireEvaluation:
        """Evaluate content entry against the current session's active phase."""
        state = self.get_or_create_state(session_id)
        return self._gate_evaluator.evaluate_admission(
            current_phase=state.current_phase,
            intended_phase=intended_phase,
            content_length=content_length,
            is_single_use=is_single_use,
            has_trigger_condition=has_trigger_condition,
            trigger_satisfied=trigger_satisfied,
            can_external_lookup=can_external_lookup,
        )

    def attach_exploration_handoff(
        self,
        session_id: str,
        handoff: StructuredExplorationHandoff,
    ) -> PhaseLifecycleState:
        """Store compact <= 500 char exploration handoff into the session's clean retainment pool."""
        state = self.get_or_create_state(session_id)
        updated_handoffs = list(state.retained_handoffs)
        updated_handoffs.append(handoff)

        new_state = PhaseLifecycleState(
            session_id=session_id,
            current_phase=state.current_phase,
            active_deliverable_templates=list(state.active_deliverable_templates),
            retained_handoffs=updated_handoffs,
            purged_raw_tokens_count=state.purged_raw_tokens_count,
        )
        self._session_states[session_id] = new_state
        return new_state

    def get_global_telemetry(self) -> dict[str, object]:
        """Aggregate cross-session lifecycle telemetry."""
        total_handoffs = sum(len(s.retained_handoffs) for s in self._session_states.values())
        return {
            "active_sessions": len(self._session_states),
            "total_exploration_handoffs": total_handoffs,
            "total_purged_raw_tokens": self._total_purged_tokens,
        }
