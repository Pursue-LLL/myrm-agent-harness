"""
[POS] src/myrm_agent_harness/core/security/auto_review_resolution/four_way_state_machine.py
[INPUT] threading, time, typing, .types (DenialDiagnosticPayload, ResolutionBranchEnum, ResolutionDecisionRecord)
[OUTPUT] FourWayResolutionStateMachine

Manages four-way adaptive resolution state transitions and prevents isomorphic retry loops
when agents encounter security auto-review denials.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
import time

from .types import (
    DenialDiagnosticPayload,
    ResolutionBranchEnum,
    ResolutionDecisionRecord,
)


class FourWayResolutionStateMachine:
    """Coordinates four-way adaptive resolution state transitions and enforces loop breaking."""

    def __init__(self, max_isomorphic_attempts: int = 2) -> None:
        self._lock = threading.RLock()
        self._max_isomorphic_attempts = max_isomorphic_attempts
        self._active_denials: dict[str, DenialDiagnosticPayload] = {}  # session_id -> latest
        self._action_attempt_counts: dict[str, dict[str, int]] = {}  # session_id -> action -> count
        self._decision_history: dict[str, list[ResolutionDecisionRecord]] = {}  # session_id -> history

    def register_denial(self, session_id: str, diagnostic: DenialDiagnosticPayload) -> None:
        """Register a new auto-review denial for a session context."""
        with self._lock:
            self._active_denials[session_id] = diagnostic
            if session_id not in self._action_attempt_counts:
                self._action_attempt_counts[session_id] = {}
            current_count = self._action_attempt_counts[session_id].get(diagnostic.blocked_action, 0)
            self._action_attempt_counts[session_id][diagnostic.blocked_action] = current_count + 1

    def get_active_denial(self, session_id: str) -> DenialDiagnosticPayload | None:
        """Retrieve latest pending denial diagnostic for a session."""
        with self._lock:
            return self._active_denials.get(session_id)

    def evaluate_effective_branch(
        self, session_id: str, proposed_branch: ResolutionBranchEnum
    ) -> tuple[ResolutionBranchEnum, str]:
        """Evaluate if proposed branch is safe or if loop-breaker must force handover or stop.

        Returns:
            Tuple of (effective_branch, explanation)
        """
        with self._lock:
            diag = self._active_denials.get(session_id)
            if diag is None:
                return proposed_branch, "No active denial in session context."

            action = diag.blocked_action
            attempts = self._action_attempt_counts.get(session_id, {}).get(action, 0)

            # Isomorphic retry loop breaker: If agent keeps trying alternatives for the same blocked action
            if proposed_branch == ResolutionBranchEnum.TRY_ALTERNATIVE and attempts > self._max_isomorphic_attempts:
                return (
                    ResolutionBranchEnum.HANDOVER_TO_USER,
                    (
                        f"Loop breaker engaged: Action '{action}' blocked {attempts} times. "
                        "Alternatives exhausted. Forcing HANDOVER_TO_USER to prevent infinite retry deadlocks."
                    ),
                )

            return proposed_branch, f"Permitted resolution branch: {proposed_branch.value}."

    def commit_resolution_decision(
        self,
        session_id: str,
        chosen_branch: ResolutionBranchEnum,
        rationale: str,
        alternative_attempted: str | None = None,
        handover_id: str | None = None,
    ) -> ResolutionDecisionRecord:
        """Record agent's final decision for current denial and clear active denial slot."""
        now = time.time()
        with self._lock:
            diag = self._active_denials.pop(session_id, None)
            diag_id = diag.diagnostic_id if diag else "no-active-denial"

            record = ResolutionDecisionRecord(
                session_id=session_id,
                diagnostic_id=diag_id,
                chosen_branch=chosen_branch,
                decision_rationale=rationale,
                timestamp=now,
                alternative_attempted=alternative_attempted,
                handover_id=handover_id,
            )

            if session_id not in self._decision_history:
                self._decision_history[session_id] = []
            self._decision_history[session_id].append(record)

            # If resolved or stopped, reset attempts count for that action
            if (
                chosen_branch in (ResolutionBranchEnum.STOP_OPERATION, ResolutionBranchEnum.HANDOVER_TO_USER)
                and session_id in self._action_attempt_counts
                and diag is not None
            ):
                self._action_attempt_counts[session_id].pop(diag.blocked_action, None)

            return record

    def get_history(self, session_id: str) -> list[ResolutionDecisionRecord]:
        """Retrieve full decision trail for a session."""
        with self._lock:
            return list(self._decision_history.get(session_id, []))
