# [POS]: myrm_agent_harness/agent/context_management/handoff/engine.py
# [INPUT]: AgentHandoffStore, ExactlyOnceHandoffMachine, SessionFinalizer, types
# [OUTPUT]: AgentHandoffEngine
"""Unified facade for agent handoff management, exactly-once claim, and session finalization.

Provides high-level APIs for finalizing sessions, claiming handoffs under strict
mutual exclusion, tracking state transitions, and querying durable handoff memoranda.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from myrm_agent_harness.agent.context_management.handoff.finalizer import SessionFinalizer
from myrm_agent_harness.agent.context_management.handoff.handoff_store import AgentHandoffStore
from myrm_agent_harness.agent.context_management.handoff.state_machine import ExactlyOnceHandoffMachine
from myrm_agent_harness.agent.context_management.handoff.types import (
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
