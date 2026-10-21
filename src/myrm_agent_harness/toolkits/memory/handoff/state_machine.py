"""State machine governing exactly-once claim and state transitions for agent handoffs.

Enforces mutual exclusion during handoff claiming, guaranteeing that multiple
concurrent successor agents cannot race to claim the same memorandum.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.handoff.handoff_store::AgentHandoffStore (POS: Persistent storage backend for
  agent handoff packets.)
- toolkits.memory.handoff.types::AgentHandoffSpec, HandoffClaimReceipt, HandoffStatus (POS: Type
  definitions for cross-agent/cross-session typed handoff protocol.)

[OUTPUT]
- HandoffError: Base exception for handoff protocol violations.
- HandoffNotFoundError: Raised when the requested handoff ID is not registered.
- HandoffAlreadyClaimedError: Raised when attempting to claim an already claimed or locked handoff.
- HandoffAlreadyCompletedError: Raised when an operation is attempted on an already finalized/completed
  handoff.
- HandoffTargetMismatchError: Raised when the claiming profile is not the targeted profile specified in
  contract.
- HandoffInvalidTransitionError: Raised when an invalid state transition is attempted.
- ExactlyOnceHandoffMachine: Atomic state machine guaranteeing exactly-once claim and linear transitions.

[POS]
State machine governing exactly-once claim and state transitions for agent handoffs.
"""

from __future__ import annotations

import logging
import threading
import time

from myrm_agent_harness.toolkits.memory.handoff.handoff_store import AgentHandoffStore
from myrm_agent_harness.toolkits.memory.handoff.types import (
    AgentHandoffSpec,
    HandoffClaimReceipt,
    HandoffStatus,
)

logger = logging.getLogger(__name__)


class HandoffError(Exception):
    """Base exception for handoff protocol violations."""


class HandoffNotFoundError(HandoffError):
    """Raised when the requested handoff ID is not registered."""


class HandoffAlreadyClaimedError(HandoffError):
    """Raised when attempting to claim an already claimed or locked handoff."""


class HandoffAlreadyCompletedError(HandoffError):
    """Raised when an operation is attempted on an already finalized/completed handoff."""


class HandoffTargetMismatchError(HandoffError):
    """Raised when the claiming profile is not the targeted profile specified in contract."""


class HandoffInvalidTransitionError(HandoffError):
    """Raised when an invalid state transition is attempted."""


class ExactlyOnceHandoffMachine:
    """Atomic state machine guaranteeing exactly-once claim and linear transitions."""

    def __init__(self, store: AgentHandoffStore) -> None:
        self._store = store
        self._lock = threading.RLock()

    def claim(
        self,
        handoff_id: str,
        claimer_profile_id: str,
        claimer_session_id: str,
    ) -> HandoffClaimReceipt:
        """Atomically claim a pending handoff, preventing race conditions.

        Args:
            handoff_id: Unique handoff specification ID to claim.
            claimer_profile_id: Profile ID of the successor agent.
            claimer_session_id: Session ID of the successor context.

        Returns:
            HandoffClaimReceipt proving exclusive atomic acquisition.

        Raises:
            HandoffNotFoundError: If the handoff does not exist.
            HandoffAlreadyClaimedError: If already claimed.
            HandoffAlreadyCompletedError: If already completed.
            HandoffTargetMismatchError: If designated recipient does not match.
            HandoffInvalidTransitionError: For any other non-pending state.
        """
        with self._lock:
            spec = self._store.get(handoff_id)
            if spec is None:
                raise HandoffNotFoundError(f"Handoff packet '{handoff_id}' does not exist.")

            if spec.status == HandoffStatus.CLAIMED:
                raise HandoffAlreadyClaimedError(
                    f"Handoff '{handoff_id}' is already claimed by {spec.claimed_by_profile_id}."
                )
            if spec.status == HandoffStatus.COMPLETED:
                raise HandoffAlreadyCompletedError(f"Handoff '{handoff_id}' has already been marked completed.")
            if spec.status != HandoffStatus.PENDING:
                raise HandoffInvalidTransitionError(f"Cannot claim handoff in state '{spec.status.value}'.")

            # Profile contract enforcement
            if spec.target_profile_id is not None and spec.target_profile_id != claimer_profile_id:
                raise HandoffTargetMismatchError(
                    f"Handoff targeted profile '{spec.target_profile_id}', but claimed by '{claimer_profile_id}'."
                )

            # CAS: Atomically update status
            success = self._store.update_status(
                handoff_id=handoff_id,
                new_status=HandoffStatus.CLAIMED,
                claimed_by_profile_id=claimer_profile_id,
                claimed_by_session_id=claimer_session_id,
            )
            if not success:
                raise HandoffInvalidTransitionError(
                    f"Failed to persist atomic transition to CLAIMED for '{handoff_id}'."
                )

            updated_spec = self._store.get(handoff_id)
            if updated_spec is None:
                raise HandoffNotFoundError(f"Handoff '{handoff_id}' disappeared after claim.")

            receipt = HandoffClaimReceipt(
                handoff_id=handoff_id,
                claimed_by_profile_id=claimer_profile_id,
                claimed_by_session_id=claimer_session_id,
                claim_timestamp=time.time(),
                handoff_spec=updated_spec,
            )
            logger.info(
                "Handoff '%s' claimed by profile '%s' in session '%s'",
                handoff_id,
                claimer_profile_id,
                claimer_session_id,
            )
            return receipt

    def complete(
        self,
        handoff_id: str,
        completing_session_id: str,
    ) -> AgentHandoffSpec:
        """Mark a claimed handoff memorandum as completed.

        Args:
            handoff_id: Unique handoff specification ID.
            completing_session_id: Session ID performing completion.

        Returns:
            Updated AgentHandoffSpec with COMPLETED state.
        """
        with self._lock:
            spec = self._store.get(handoff_id)
            if spec is None:
                raise HandoffNotFoundError(f"Handoff packet '{handoff_id}' does not exist.")

            if spec.status == HandoffStatus.COMPLETED:
                return spec

            if spec.status != HandoffStatus.CLAIMED:
                raise HandoffInvalidTransitionError(
                    f"Cannot complete handoff in state '{spec.status.value}', must be CLAIMED."
                )

            if spec.claimed_by_session_id is not None and spec.claimed_by_session_id != completing_session_id:
                raise HandoffInvalidTransitionError(
                    f"Session '{completing_session_id}' did not claim handoff '{handoff_id}' "
                    f"(claimed by '{spec.claimed_by_session_id}')."
                )

            self._store.update_status(
                handoff_id=handoff_id,
                new_status=HandoffStatus.COMPLETED,
            )

            updated = self._store.get(handoff_id)
            if updated is None:
                raise HandoffNotFoundError(f"Handoff '{handoff_id}' disappeared after completion.")
            logger.info("Handoff '%s' marked completed by session '%s'", handoff_id, completing_session_id)
            return updated

    def cancel(
        self,
        handoff_id: str,
        cancelling_session_id: str,
        reason: str,
    ) -> AgentHandoffSpec:
        """Cancel an existing pending or claimed handoff packet."""
        with self._lock:
            spec = self._store.get(handoff_id)
            if spec is None:
                raise HandoffNotFoundError(f"Handoff packet '{handoff_id}' does not exist.")

            if spec.status == HandoffStatus.COMPLETED:
                raise HandoffAlreadyCompletedError(f"Cannot cancel completed handoff '{handoff_id}'.")

            self._store.update_status(
                handoff_id=handoff_id,
                new_status=HandoffStatus.CANCELLED,
            )
            updated = self._store.get(handoff_id)
            if updated is None:
                raise HandoffNotFoundError(f"Handoff '{handoff_id}' disappeared after cancellation.")
            logger.info(
                "Handoff '%s' cancelled by session '%s', reason: %s",
                handoff_id,
                cancelling_session_id,
                reason,
            )
            return updated
