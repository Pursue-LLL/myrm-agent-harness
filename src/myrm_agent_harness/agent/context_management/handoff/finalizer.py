# [POS]: myrm_agent_harness/agent/context_management/handoff/finalizer.py
# [INPUT]: AgentHandoffStore, FinalizeSessionRequest, FinalizeSessionResult, AgentHandoffSpec
# [OUTPUT]: SessionFinalizer
"""Session finalizer responsible for extracting and persisting durable handoffs upon session close.

Ensures no execution state, rejected hypotheses, or latent constraints are lost
when an agent finishes its work or prepares to hand off execution.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time

from myrm_agent_harness.agent.context_management.handoff.handoff_store import AgentHandoffStore
from myrm_agent_harness.agent.context_management.handoff.types import (
    AgentHandoffSpec,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    HandoffStatus,
)

logger = logging.getLogger(__name__)


class SessionFinalizationError(Exception):
    """Raised when session finalization fails validation or persistence."""


class SessionFinalizer:
    """Finalizes an agent session, converting working memory into a durable handoff packet."""

    def __init__(self, store: AgentHandoffStore) -> None:
        self._store = store

    def finalize(self, request: FinalizeSessionRequest) -> FinalizeSessionResult:
        """Finalize session state into a durable handoff memorandum.

        Args:
            request: Typed finalization request containing active goals and context.

        Returns:
            FinalizeSessionResult with durable storage location and handoff ID.

        Raises:
            SessionFinalizationError: If parameters are invalid or storage fails.
        """
        if not request.session_id.strip():
            raise SessionFinalizationError("session_id must not be empty.")
        if not request.source_profile_id.strip():
            raise SessionFinalizationError("source_profile_id must not be empty.")
        if not request.active_goal.strip():
            raise SessionFinalizationError("active_goal must not be empty.")

        now = time.time()
        spec = AgentHandoffSpec(
            session_id=request.session_id.strip(),
            source_profile_id=request.source_profile_id.strip(),
            target_profile_id=request.target_profile_id.strip() if request.target_profile_id else None,
            active_goal=request.active_goal.strip(),
            failed_approaches=list(request.failed_approaches),
            implicit_constraints=list(request.implicit_constraints),
            errors_and_fixes=list(request.errors_and_fixes),
            pending_asks=list(request.pending_asks),
            next_actions=list(request.next_actions),
            status=HandoffStatus.PENDING,
            created_at=now,
        )

        persisted_path = self._store.save(spec)
        path_str = str(persisted_path) if persisted_path is not None else "in-memory"

        logger.info(
            "Session '%s' finalized successfully into handoff '%s' at '%s'",
            request.session_id,
            spec.handoff_id,
            path_str,
        )

        return FinalizeSessionResult(
            session_id=request.session_id,
            handoff_id=spec.handoff_id,
            persisted_path=path_str,
            status=HandoffStatus.PENDING,
            timestamp=now,
        )
