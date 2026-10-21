"""Unified facade for agent handoff management, exactly-once claim, and session finalization.

Provides high-level APIs for finalizing sessions, claiming handoffs under strict
mutual exclusion, tracking state transitions, and querying durable handoff memoranda.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.handoff.finalizer::SessionFinalizer (POS: Session finalizer responsible for
  extracting and persisting durable handoffs upon session close.)
- toolkits.memory.handoff.handoff_store::AgentHandoffStore (POS: Persistent storage backend for
  agent handoff packets.)
- toolkits.memory.handoff.state_machine::ExactlyOnceHandoffMachine (POS: State machine governing
  exactly-once claim and state transitions for agent handoffs.)
- toolkits.memory.handoff.types::AgentHandoffSpec, FinalizeSessionRequest, FinalizeSessionResult,
  HandoffClaimReceipt (POS: Type definitions for cross-agent/cross-session typed handoff protocol.)

[OUTPUT]
- AgentHandoffEngine: Unified engine encapsulating storage, state machine, and session finalizer.

[POS]
Unified facade for agent handoff management, exactly-once claim, and session finalization.
"""

from __future__ import annotations

import logging
from pathlib import Path

from myrm_agent_harness.toolkits.memory.handoff.finalizer import SessionFinalizer
from myrm_agent_harness.toolkits.memory.handoff.handoff_store import AgentHandoffStore
from myrm_agent_harness.toolkits.memory.handoff.state_machine import ExactlyOnceHandoffMachine
from myrm_agent_harness.toolkits.memory.handoff.types import (
    AgentHandoffSpec,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    HandoffClaimReceipt,
)

logger = logging.getLogger(__name__)


class AgentHandoffEngine:
    """Unified engine encapsulating storage, state machine, and session finalizer."""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        self.store = AgentHandoffStore(storage_dir=storage_dir)
        self.state_machine = ExactlyOnceHandoffMachine(self.store)
        self.finalizer = SessionFinalizer(self.store)
        logger.info("AgentHandoffEngine initialized with storage_dir=%s", storage_dir)

    def finalize_session(self, request: FinalizeSessionRequest) -> FinalizeSessionResult:
        """Finalize an agent session and create an immutable durable handoff memorandum."""
        return self.finalizer.finalize(request)

    def claim_handoff(
        self,
        handoff_id: str,
        claimer_profile_id: str,
        claimer_session_id: str,
    ) -> HandoffClaimReceipt:
        """Atomically claim a pending handoff for a successor agent."""
        return self.state_machine.claim(
            handoff_id=handoff_id,
            claimer_profile_id=claimer_profile_id,
            claimer_session_id=claimer_session_id,
        )

    def complete_handoff(
        self,
        handoff_id: str,
        completing_session_id: str,
    ) -> AgentHandoffSpec:
        """Mark a claimed handoff memorandum as completed by the successor."""
        return self.state_machine.complete(
            handoff_id=handoff_id,
            completing_session_id=completing_session_id,
        )

    def cancel_handoff(
        self,
        handoff_id: str,
        cancelling_session_id: str,
        reason: str,
    ) -> AgentHandoffSpec:
        """Cancel a pending or claimed handoff."""
        return self.state_machine.cancel(
            handoff_id=handoff_id,
            cancelling_session_id=cancelling_session_id,
            reason=reason,
        )

    def get_handoff(self, handoff_id: str) -> AgentHandoffSpec | None:
        """Retrieve a handoff memorandum by ID."""
        return self.store.get(handoff_id)

    def list_pending(self, target_profile_id: str | None = None) -> list[AgentHandoffSpec]:
        """List all unassigned or target-matching pending handoffs."""
        return self.store.list_pending(target_profile_id=target_profile_id)

    def list_by_session(self, session_id: str) -> list[AgentHandoffSpec]:
        """List all handoffs associated with a given session ID."""
        return self.store.list_by_session(session_id=session_id)
