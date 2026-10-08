"""
[POS] src/myrm_agent_harness/core/security/auto_review_resolution/facade.py
[INPUT] threading, typing, .diagnostic_reporter, .four_way_state_machine, .handover_deck_manager, .types
[OUTPUT] AutoReviewResolutionFacade

Unified Facade for Auto-Review Denial Four-Way Adaptive Resolution State Machine Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .diagnostic_reporter import DenialDiagnosticReporter
from .four_way_state_machine import FourWayResolutionStateMachine
from .handover_deck_manager import HandoverDeckManager
from .types import (
    AutoReviewResolutionMetrics,
    DenialDiagnosticPayload,
    DenialReasonCodeEnum,
    HandoverDeckPayload,
    HandoverStatusEnum,
    ResolutionBranchEnum,
    ResolutionDecisionRecord,
)


class AutoReviewResolutionFacade:
    """Coordinates denial diagnostics, 4-way adaptive resolution state machine, and handover cards."""

    def __init__(self, max_isomorphic_attempts: int = 2) -> None:
        self._lock = threading.RLock()
        self._reporter = DenialDiagnosticReporter()
        self._state_machine = FourWayResolutionStateMachine(
            max_isomorphic_attempts=max_isomorphic_attempts
        )
        self._deck_manager = HandoverDeckManager()
        self._metrics = AutoReviewResolutionMetrics()

    def report_and_register_denial(
        self,
        session_id: str,
        blocked_action: str,
        denial_reason: str,
        reason_code: DenialReasonCodeEnum,
        policy_rule_id: str,
        context_data: dict[str, str] | None = None,
        custom_alternatives: list[str] | None = None,
        custom_suggested_branch: ResolutionBranchEnum | None = None,
    ) -> DenialDiagnosticPayload:
        """Create structured denial diagnostic and register into session state machine."""
        diag = self._reporter.generate_diagnostic(
            blocked_action=blocked_action,
            denial_reason=denial_reason,
            reason_code=reason_code,
            policy_rule_id=policy_rule_id,
            context_data=context_data,
            custom_alternatives=custom_alternatives,
            custom_suggested_branch=custom_suggested_branch,
        )
        with self._lock:
            self._state_machine.register_denial(session_id, diag)
            self._metrics.total_denials_processed += 1
        return diag

    def get_active_denial(self, session_id: str) -> DenialDiagnosticPayload | None:
        """Retrieve active pending denial diagnostic for a session."""
        return self._state_machine.get_active_denial(session_id)

    def evaluate_branch(
        self, session_id: str, proposed_branch: ResolutionBranchEnum
    ) -> tuple[ResolutionBranchEnum, str]:
        """Evaluate if proposed resolution branch is permissible or if loop-breaker must divert."""
        return self._state_machine.evaluate_effective_branch(session_id, proposed_branch)

    def stage_handover_deck(
        self,
        session_id: str,
        task_description: str,
        prepared_command: str,
        parameters: dict[str, str],
        guidance_notes: str,
    ) -> HandoverDeckPayload:
        """Create and stage an interactive human handover card."""
        return self._deck_manager.stage_handover(
            session_id=session_id,
            task_description=task_description,
            prepared_command=prepared_command,
            parameters=parameters,
            guidance_notes=guidance_notes,
        )

    def get_handover(self, handover_id: str) -> HandoverDeckPayload | None:
        """Inspect a staged handover deck."""
        return self._deck_manager.get_handover(handover_id)

    def list_staged_handovers(self, session_id: str | None = None) -> list[HandoverDeckPayload]:
        """List active staged handover cards."""
        return self._deck_manager.list_staged_handovers(session_id)

    def execute_handover(self, handover_id: str) -> HandoverDeckPayload | None:
        """User releases and executes pre-staged handover action."""
        deck = self._deck_manager.execute_handover(handover_id)
        if deck is not None and deck.status == HandoverStatusEnum.EXECUTED_BY_USER:
            with self._lock:
                self._metrics.handovers_executed_by_user += 1
        return deck

    def dismiss_handover(self, handover_id: str) -> HandoverDeckPayload | None:
        """User dismisses or cancels pre-staged handover action."""
        deck = self._deck_manager.dismiss_handover(handover_id)
        if deck is not None and deck.status == HandoverStatusEnum.DISMISSED_BY_USER:
            with self._lock:
                self._metrics.handovers_dismissed_by_user += 1
        return deck

    def commit_resolution(
        self,
        session_id: str,
        chosen_branch: ResolutionBranchEnum,
        rationale: str,
        alternative_attempted: str | None = None,
        handover_id: str | None = None,
    ) -> ResolutionDecisionRecord:
        """Record agent's final resolution branch decision and update telemetry counters."""
        record = self._state_machine.commit_resolution_decision(
            session_id=session_id,
            chosen_branch=chosen_branch,
            rationale=rationale,
            alternative_attempted=alternative_attempted,
            handover_id=handover_id,
        )
        with self._lock:
            if chosen_branch == ResolutionBranchEnum.ASK_USER:
                self._metrics.branch_ask_user_count += 1
            elif chosen_branch == ResolutionBranchEnum.TRY_ALTERNATIVE:
                self._metrics.branch_alternative_count += 1
            elif chosen_branch == ResolutionBranchEnum.HANDOVER_TO_USER:
                self._metrics.branch_handover_count += 1
            elif chosen_branch == ResolutionBranchEnum.STOP_OPERATION:
                self._metrics.branch_stop_count += 1
        return record

    def get_resolution_history(self, session_id: str) -> list[ResolutionDecisionRecord]:
        """Retrieve audit history of resolution decisions."""
        return self._state_machine.get_history(session_id)

    def get_metrics(self) -> AutoReviewResolutionMetrics:
        """Retrieve snapshot of operational metrics."""
        with self._lock:
            return AutoReviewResolutionMetrics(
                total_denials_processed=self._metrics.total_denials_processed,
                branch_ask_user_count=self._metrics.branch_ask_user_count,
                branch_alternative_count=self._metrics.branch_alternative_count,
                branch_handover_count=self._metrics.branch_handover_count,
                branch_stop_count=self._metrics.branch_stop_count,
                handovers_executed_by_user=self._metrics.handovers_executed_by_user,
                handovers_dismissed_by_user=self._metrics.handovers_dismissed_by_user,
            )


_global_auto_review_facade: AutoReviewResolutionFacade | None = None


def get_auto_review_resolution_facade() -> AutoReviewResolutionFacade:
    """Return process-wide singleton AutoReviewResolutionFacade instance."""
    global _global_auto_review_facade
    if _global_auto_review_facade is None:
        _global_auto_review_facade = AutoReviewResolutionFacade()
    return _global_auto_review_facade
