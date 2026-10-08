"""Desktop Action Safe Enclave Gate for intercepting critical actions and handling emergency panic.

[INPUT]
- CriticalDesktopAction, ActionEnclaveChallenge
- CriticalActionSemanticMatcher, DesktopActionAuditDeck

[OUTPUT]
- DesktopActionEnclaveGate: interception gate, panic control, challenge lifecycle manager.

[POS]
- Harness core security gate for Computer-Use agents.
"""

from __future__ import annotations

import threading
import time
import uuid

from myrm_agent_harness.core.security.desktop_enclave.audit_deck import DesktopActionAuditDeck
from myrm_agent_harness.core.security.desktop_enclave.semantic_matcher import (
    CriticalActionSemanticMatcher,
)
from myrm_agent_harness.core.security.desktop_enclave.types import (
    ActionEnclaveChallenge,
    CriticalActionBlockedError,
    CriticalDesktopAction,
    DesktopActionPanickedError,
    DesktopActionRiskLevel,
)


class DesktopActionEnclaveGate:
    """Interception gate enforcing human-in-the-loop sign-off on critical desktop actions."""

    def __init__(
        self,
        audit_deck: DesktopActionAuditDeck | None = None,
        require_suspicious_confirmation: bool = False,
    ) -> None:
        self._audit_deck = audit_deck or DesktopActionAuditDeck()
        self._require_suspicious_confirmation = require_suspicious_confirmation
        self._challenges: dict[str, ActionEnclaveChallenge] = {}
        self._panicked: bool = False
        self._panic_reason: str = ""
        self._lock = threading.Lock()

    @property
    def audit_deck(self) -> DesktopActionAuditDeck:
        """Underlying telemetry audit deck."""
        return self._audit_deck

    @property
    def is_panicked(self) -> bool:
        """Whether emergency panic stop is currently active."""
        with self._lock:
            return self._panicked

    @property
    def panic_reason(self) -> str:
        """Reason description for active panic stop."""
        with self._lock:
            return self._panic_reason

    def trigger_panic(self, reason: str = "User manual emergency stop activated") -> None:
        """Instantly trip the circuit breaker and freeze all desktop agent actions."""
        with self._lock:
            self._panicked = True
            self._panic_reason = reason
            # Invalidate all pending challenges
            for cid, ch in list(self._challenges.items()):
                if ch.status == "pending":
                    self._challenges[cid] = ActionEnclaveChallenge(
                        challenge_id=ch.challenge_id,
                        action=ch.action,
                        reason=f"Aborted by panic: {reason}",
                        status="panicked",
                        created_at=ch.created_at,
                    )

    def reset_panic(self) -> None:
        """Reset the panic circuit breaker back to normal operational state."""
        with self._lock:
            self._panicked = False
            self._panic_reason = ""

    def evaluate_action(
        self, action: CriticalDesktopAction
    ) -> tuple[bool, ActionEnclaveChallenge | None]:
        """Evaluate an impending action against semantic policies and panic state.

        Returns:
            (is_allowed_immediately, challenge_if_intercepted)

        Raises:
            DesktopActionPanickedError: If panic mode is active.
        """
        with self._lock:
            if self._panicked:
                self._audit_deck.record_action(
                    record_id=f"rec_{uuid.uuid4().hex[:8]}",
                    action=action,
                    enclave_verified=False,
                    executed=False,
                    execution_latency_ms=0.0,
                    status="panicked_aborted",
                )
                raise DesktopActionPanickedError(self._panic_reason)

        risk_level, category, reason = CriticalActionSemanticMatcher.evaluate(action)

        # Update action with classified risk level
        classified_action = CriticalDesktopAction(
            action_id=action.action_id,
            action_type=action.action_type,
            semantic_intent=action.semantic_intent,
            coordinates=action.coordinates,
            target_element_text=action.target_element_text,
            payload_text=action.payload_text,
            risk_level=risk_level,
            timestamp=action.timestamp,
        )

        should_challenge = risk_level == DesktopActionRiskLevel.CRITICAL or (
            risk_level == DesktopActionRiskLevel.SUSPICIOUS
            and self._require_suspicious_confirmation
        )

        if not should_challenge:
            self._audit_deck.record_action(
                record_id=f"rec_{uuid.uuid4().hex[:8]}",
                action=classified_action,
                enclave_verified=True,
                executed=False,
                execution_latency_ms=0.0,
                status="pre_evaluated_safe",
            )
            return True, None

        challenge_id = f"chal_{uuid.uuid4().hex[:10]}"
        challenge = ActionEnclaveChallenge(
            challenge_id=challenge_id,
            action=classified_action,
            reason=f"[{category}] {reason}",
            status="pending",
            created_at=time.time(),
        )

        with self._lock:
            self._challenges[challenge_id] = challenge

        self._audit_deck.record_action(
            record_id=f"rec_{uuid.uuid4().hex[:8]}",
            action=classified_action,
            enclave_verified=False,
            executed=False,
            execution_latency_ms=0.0,
            status="challenged_pending_review",
        )
        return False, challenge

    def approve_challenge(self, challenge_id: str) -> CriticalDesktopAction:
        """Human approval for intercepted critical desktop action."""
        with self._lock:
            if self._panicked:
                raise DesktopActionPanickedError(self._panic_reason)

            challenge = self._challenges.get(challenge_id)
            if not challenge:
                raise KeyError(f"Challenge '{challenge_id}' not found")
            if challenge.status != "pending":
                raise ValueError(
                    f"Challenge '{challenge_id}' cannot be approved in state '{challenge.status}'"
                )

            approved = ActionEnclaveChallenge(
                challenge_id=challenge.challenge_id,
                action=challenge.action,
                reason=challenge.reason,
                status="approved",
                created_at=challenge.created_at,
            )
            self._challenges[challenge_id] = approved

        self._audit_deck.record_action(
            record_id=f"rec_{uuid.uuid4().hex[:8]}",
            action=approved.action,
            enclave_verified=True,
            executed=False,
            execution_latency_ms=0.0,
            status="challenge_approved",
        )
        return approved.action

    def reject_challenge(self, challenge_id: str, reason: str = "User denied action") -> None:
        """Reject and cancel intercepted desktop action."""
        with self._lock:
            challenge = self._challenges.get(challenge_id)
            if not challenge:
                raise KeyError(f"Challenge '{challenge_id}' not found")
            if challenge.status != "pending":
                raise ValueError(
                    f"Challenge '{challenge_id}' cannot be rejected in state '{challenge.status}'"
                )

            rejected = ActionEnclaveChallenge(
                challenge_id=challenge.challenge_id,
                action=challenge.action,
                reason=f"Rejected: {reason}",
                status="rejected",
                created_at=challenge.created_at,
            )
            self._challenges[challenge_id] = rejected

        self._audit_deck.record_action(
            record_id=f"rec_{uuid.uuid4().hex[:8]}",
            action=rejected.action,
            enclave_verified=False,
            executed=False,
            execution_latency_ms=0.0,
            status="challenge_rejected",
        )
        raise CriticalActionBlockedError(challenge.action.action_id, reason)

    def get_challenge(self, challenge_id: str) -> ActionEnclaveChallenge | None:
        """Get challenge details by ID."""
        with self._lock:
            return self._challenges.get(challenge_id)

    def list_pending_challenges(self) -> list[ActionEnclaveChallenge]:
        """List all currently pending challenges awaiting sign-off."""
        with self._lock:
            return [ch for ch in self._challenges.values() if ch.status == "pending"]
