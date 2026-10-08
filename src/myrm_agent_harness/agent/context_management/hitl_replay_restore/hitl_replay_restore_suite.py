# [INPUT]: hitl_replay_restore_engine.py, hitl_replay_types.py, passive_replay_scanner.py
# [OUTPUT]: CopilotKitHITLReplayRestoreSuite
# [POS]: agent/context_management/hitl_replay_restore/hitl_replay_restore_suite.py

"""Unified orchestration facade for reconnect passive replay filtering and HITL restoration.

[INPUT]
- agent.context_management.hitl_replay_restore.hitl_replay_restore_engine::HITLReplayRestoreEngine
  (POS: Core engine managing replay processing and pending queues.)
- agent.context_management.hitl_replay_restore.hitl_replay_types::HITLApprovalState,
  PendingHITLDescriptor, ReplayRestorationSummary, ToolCallReplayItem, ToolExecutionType,
  ToolResultReplayItem (POS: Strongly typed domain models.)
- agent.context_management.hitl_replay_restore.passive_replay_scanner::PassiveReplayScanner
  (POS: Scanner analyzing replay frames.)

[OUTPUT]
- CopilotKitHITLReplayRestoreSuite: High-level facade executing selective replay analysis,
  ordinary tool side-effect suppression, and pending approval restoration.

[POS]
Main entry facade for reconnect passive replay and human-in-the-loop restoration.
"""

from __future__ import annotations

from .hitl_replay_restore_engine import HITLReplayRestoreEngine
from .hitl_replay_types import (
    HITLApprovalState,
    PendingHITLDescriptor,
    ReplayRestorationSummary,
    ToolCallReplayItem,
    ToolExecutionType,
    ToolResultReplayItem,
)
from .passive_replay_scanner import PassiveReplayScanner


class CopilotKitHITLReplayRestoreSuite:
    """Unified facade managing reconnect passive replay and human-in-the-loop approval restoration."""

    def __init__(self, engine: HITLReplayRestoreEngine | None = None) -> None:
        self._engine = engine or HITLReplayRestoreEngine()

    @property
    def engine(self) -> HITLReplayRestoreEngine:
        """Access underlying restoration engine."""
        return self._engine

    def handle_reconnect_replay(
        self,
        session_id: str,
        tool_calls: list[ToolCallReplayItem],
        tool_results: list[ToolResultReplayItem],
    ) -> ReplayRestorationSummary:
        """Process passive replay stream during reconnection.

        Ordinary side-effect tools are suppressed and kept passive,
        completed HITL interactions are skipped without reopening,
        and un-answered pending HITL items are restored for user decision.

        Args:
            session_id: Session identifier.
            tool_calls: Historical tool call requests in replay stream.
            tool_results: Historical tool results in replay stream.

        Returns:
            ReplayRestorationSummary report.
        """
        return self._engine.process_reconnect_replay(
            session_id=session_id,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )

    def list_pending_approvals(self, session_id: str) -> list[PendingHITLDescriptor]:
        """List active pending approvals awaiting user decision in a session."""
        return self._engine.list_pending_hitl(session_id=session_id)

    def resolve_hitl_approval(
        self,
        session_id: str,
        tool_call_id: str,
        approved: bool,
        response_content: str,
    ) -> ToolResultReplayItem:
        """Submit approval decision to resolve a pending HITL item."""
        return self._engine.submit_approval_decision(
            session_id=session_id,
            tool_call_id=tool_call_id,
            approved=approved,
            response_content=response_content,
        )

    def scan_replay_direct(
        self,
        session_id: str,
        tool_calls: list[ToolCallReplayItem],
        tool_results: list[ToolResultReplayItem],
    ) -> ReplayRestorationSummary:
        """Pure-functional direct replay scanning without queue registration."""
        return PassiveReplayScanner.scan_replay_stream(
            session_id=session_id,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )
