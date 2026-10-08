# [INPUT]: hitl_replay_types.py, passive_replay_scanner.py
# [OUTPUT]: HITLReplayRestoreEngine
# [POS]: agent/context_management/hitl_replay_restore/hitl_replay_restore_engine.py

"""Engine orchestrating selective passive replay scanning and interactive HITL resolution.

[INPUT]
- agent.context_management.hitl_replay_restore.hitl_replay_types::HITLApprovalState,
  PendingHITLDescriptor, ReplayRestorationSummary, ToolCallReplayItem, ToolResultReplayItem
  (POS: Strongly typed domain models for passive replay and HITL states.)
- agent.context_management.hitl_replay_restore.passive_replay_scanner::PassiveReplayScanner
  (POS: Replay stream scanner isolating pending HITL from ordinary tools.)

[OUTPUT]
- HITLReplayRestoreEngine: Coordinates session reconnection replay, pending approval queues,
  and decision submission.

[POS]
Lifecycle and queue coordination engine for human-in-the-loop replay restoration.
"""

from __future__ import annotations

import time

from .hitl_replay_types import (
    HITLApprovalState,
    PendingHITLDescriptor,
    ReplayRestorationSummary,
    ToolCallReplayItem,
    ToolResultReplayItem,
)
from .passive_replay_scanner import PassiveReplayScanner


class HITLReplayRestoreEngine:
    """Manages active pending HITL registrations and reconnect replay processing."""

    def __init__(self, scanner: PassiveReplayScanner | None = None) -> None:
        self._scanner = scanner or PassiveReplayScanner()
        # session_id -> {tool_call_id: PendingHITLDescriptor}
        self._pending_queues: dict[str, dict[str, PendingHITLDescriptor]] = {}
        # session_id -> list of ToolResultReplayItem (decisions rendered)
        self._decision_history: dict[str, list[ToolResultReplayItem]] = {}

    def process_reconnect_replay(
        self,
        session_id: str,
        tool_calls: list[ToolCallReplayItem],
        tool_results: list[ToolResultReplayItem],
    ) -> ReplayRestorationSummary:
        """Scan historical frames upon reconnect and register pending HITL interactions.

        Args:
            session_id: Unique session identifier.
            tool_calls: Historical tool calls from replay.
            tool_results: Historical tool results from replay.

        Returns:
            ReplayRestorationSummary detailing passive skips and restored pending items.
        """
        summary = self._scanner.scan_replay_stream(
            session_id=session_id,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )

        # Initialize or update session pending queue
        if session_id not in self._pending_queues:
            self._pending_queues[session_id] = {}

        for desc in summary.restored_pending_hitl:
            self._pending_queues[session_id][desc.tool_call_id] = desc

        return summary

    def list_pending_hitl(self, session_id: str) -> list[PendingHITLDescriptor]:
        """List all unresolved pending HITL items for a session.

        Args:
            session_id: The session identifier.

        Returns:
            List of PendingHITLDescriptor instances.
        """
        return list(self._pending_queues.get(session_id, {}).values())

    def get_pending_hitl(self, session_id: str, tool_call_id: str) -> PendingHITLDescriptor:
        """Retrieve a specific pending HITL descriptor.

        Args:
            session_id: The session identifier.
            tool_call_id: Unique tool call identifier.

        Returns:
            PendingHITLDescriptor instance.

        Raises:
            KeyError: If item is not in pending queue.
        """
        queue = self._pending_queues.get(session_id, {})
        if tool_call_id not in queue:
            msg = f"Pending HITL '{tool_call_id}' not found for session '{session_id}'."
            raise KeyError(msg)
        return queue[tool_call_id]

    def submit_approval_decision(
        self,
        session_id: str,
        tool_call_id: str,
        approved: bool,
        response_content: str,
    ) -> ToolResultReplayItem:
        """Submit user approval response to resolve a pending HITL item.

        Args:
            session_id: Unique session identifier.
            tool_call_id: The tool call being resolved.
            approved: True if user approved, False if rejected.
            response_content: Natural language or structured payload to return to model.

        Returns:
            Generated ToolResultReplayItem ready for prompt continuation.

        Raises:
            KeyError: If tool_call_id is not in pending queue.
        """
        queue = self._pending_queues.get(session_id, {})
        if tool_call_id not in queue:
            msg = f"Cannot submit decision: HITL '{tool_call_id}' is not pending in session '{session_id}'."
            raise KeyError(msg)

        now = time.time()
        # Remove from active pending queue
        queue.pop(tool_call_id)

        result_item = ToolResultReplayItem(
            tool_call_id=tool_call_id,
            content=response_content,
            is_error=not approved,
            timestamp_utc=now,
        )

        if session_id not in self._decision_history:
            self._decision_history[session_id] = []
        self._decision_history[session_id].append(result_item)

        return result_item

    def get_decision_history(self, session_id: str) -> list[ToolResultReplayItem]:
        """Retrieve resolved decisions history for a session."""
        return list(self._decision_history.get(session_id, []))
