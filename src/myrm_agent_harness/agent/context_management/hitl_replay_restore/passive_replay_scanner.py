"""Scanner performing selective replay analysis to isolate pending HITL calls from ordinary tools.

[INPUT]
- agent.context_management.hitl_replay_restore.hitl_replay_types::HITLApprovalState,
  PendingHITLDescriptor, ReplayActionKind, ReplayRestorationSummary, ToolCallReplayItem,
  ToolExecutionType, ToolResultReplayItem (POS: Strongly typed domain models.)

[OUTPUT]
- PassiveReplayScanner: Scans replay message frames to suppress ordinary tool side effects,
  skip already-answered HITL approvals, and restore un-answered pending HITL interactions.

[POS]
Replay analysis scanner isolating pending human-in-the-loop calls during reconnects.
"""

from __future__ import annotations

import time

from .hitl_replay_types import (
    HITLApprovalState,
    PendingHITLDescriptor,
    ReplayRestorationSummary,
    ToolCallReplayItem,
    ToolExecutionType,
    ToolResultReplayItem,
)


class PassiveReplayScanner:
    """Scans historical replay frames to selectively restore pending HITL while keeping ordinary tools passive."""

    @staticmethod
    def scan_replay_stream(
        session_id: str,
        tool_calls: list[ToolCallReplayItem],
        tool_results: list[ToolResultReplayItem],
    ) -> ReplayRestorationSummary:
        """Analyze replay stream and categorize tool executions.

        Args:
            session_id: The session being reconnected.
            tool_calls: Historical tool calls received in replay stream.
            tool_results: Historical tool results received in replay stream.

        Returns:
            ReplayRestorationSummary detailing passive skips and restored pending HITL.
        """
        # Map answered tool_call_ids
        answered_ids: set[str] = {res.tool_call_id for res in tool_results}

        passive_skipped = 0
        completed_hitl_skipped = 0
        restored_pending: list[PendingHITLDescriptor] = []

        now = time.time()
        for call in tool_calls:
            if call.tool_type == ToolExecutionType.ORDINARY:
                # Ordinary tools are strictly passive during reconnect replay
                passive_skipped += 1
            elif call.tool_type == ToolExecutionType.HUMAN_IN_THE_LOOP:
                if call.tool_call_id in answered_ids:
                    # Already answered HITL must NOT be reopened
                    completed_hitl_skipped += 1
                else:
                    # Unanswered HITL is restored for interactive user resolution
                    descriptor = PendingHITLDescriptor(
                        tool_call_id=call.tool_call_id,
                        tool_name=call.tool_name,
                        arguments=dict(call.arguments),
                        prompt_description=call.prompt_description,
                        registered_at_utc=call.timestamp_utc,
                        state=HITLApprovalState.PENDING,
                    )
                    restored_pending.append(descriptor)

        total_frames = len(tool_calls) + len(tool_results)

        return ReplayRestorationSummary(
            session_id=session_id,
            total_frames_processed=total_frames,
            passive_tools_skipped=passive_skipped,
            completed_hitl_skipped=completed_hitl_skipped,
            restored_pending_hitl=restored_pending,
            timestamp_utc=now,
            is_awaiting_user_approval=len(restored_pending) > 0,
        )
