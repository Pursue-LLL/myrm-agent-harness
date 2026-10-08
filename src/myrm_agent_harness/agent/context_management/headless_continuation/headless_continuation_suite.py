"""Suite orchestrating headless sandbox task continuation and mobile approval relay.

[INPUT]
- agent.context_management.headless_continuation.headless_continuation_types::ApprovalDecisionKind,
  ApprovalRelayReceipt, ClientAttachmentState, HeadlessExecutionPhase, MobileApprovalDecisionPayload,
  MobileApprovalRelayCard, ReconnectionSyncManifest, RelayChannelKind, RiskLevel (POS: Types and data
  structures for headless task continuation and mobile approval relay.)
- agent.context_management.headless_continuation.mobile_approval_relay_engine::MobileApprovalRelayEngine (POS:
  Engine generating and validating cross-device mobile approval relay cards.)

[OUTPUT]
- HeadlessContinuationSuite: Orchestrates headless task execution, mobile approvals, and desktop client
  re-synchronization.

[POS]
Suite orchestrating headless sandbox task continuation and mobile approval relay.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .headless_continuation_types import (
    ApprovalDecisionKind,
    ApprovalRelayReceipt,
    ClientAttachmentState,
    HeadlessExecutionPhase,
    MobileApprovalDecisionPayload,
    MobileApprovalRelayCard,
    ReconnectionSyncManifest,
    RelayChannelKind,
    RiskLevel,
)
from .mobile_approval_relay_engine import MobileApprovalRelayEngine


class HeadlessContinuationSuite:
    """Orchestrates headless task execution, mobile approvals, and desktop client re-synchronization."""

    def __init__(self, relay_engine: Optional[MobileApprovalRelayEngine] = None) -> None:
        self._relay_engine = relay_engine or MobileApprovalRelayEngine()
        self._client_states: Dict[str, ClientAttachmentState] = {}
        self._execution_phases: Dict[str, HeadlessExecutionPhase] = {}
        self._session_ids: Dict[str, str] = {}
        self._detach_timestamps: Dict[str, float] = {}
        self._task_outputs: Dict[str, List[str]] = {}
        self._task_receipts: Dict[str, List[ApprovalRelayReceipt]] = {}

    def register_task(self, task_id: str, session_id: str) -> None:
        """Register a new task with initial attached state."""
        self._session_ids[task_id] = session_id
        self._client_states[task_id] = ClientAttachmentState.ATTACHED
        self._execution_phases[task_id] = HeadlessExecutionPhase.IDLE
        self._task_outputs[task_id] = []
        self._task_receipts[task_id] = []

    def notify_client_detach(self, task_id: str) -> None:
        """Mark client as detached; switch task to headless running state."""
        if task_id not in self._execution_phases:
            raise KeyError(f"Task {task_id} not registered")

        self._client_states[task_id] = ClientAttachmentState.DETACHED_HEADLESS
        self._detach_timestamps[task_id] = time.time()
        if self._execution_phases[task_id] == HeadlessExecutionPhase.IDLE:
            self._execution_phases[task_id] = HeadlessExecutionPhase.RUNNING_HEADLESS

    def append_task_output(self, task_id: str, line: str) -> None:
        """Record incremental stdout/stderr output lines while running headless."""
        if task_id not in self._task_outputs:
            self._task_outputs[task_id] = []
        self._task_outputs[task_id].append(line)

    def suspend_for_approval(
        self,
        task_id: str,
        action_summary: str,
        risk_level: RiskLevel,
        ttl_seconds: int = 1800,
        channels: Optional[List[RelayChannelKind]] = None,
        preview_meta: Optional[Dict[str, str]] = None,
    ) -> MobileApprovalRelayCard:
        """Suspend headless execution and dispatch mobile relay card for human approval."""
        if task_id not in self._execution_phases:
            raise KeyError(f"Task {task_id} not registered")

        session_id = self._session_ids.get(task_id, "default-session")
        self._execution_phases[task_id] = HeadlessExecutionPhase.AWAITING_MOBILE_APPROVAL

        card = self._relay_engine.issue_relay_card(
            task_id=task_id,
            session_id=session_id,
            action_summary=action_summary,
            risk_level=risk_level,
            ttl_seconds=ttl_seconds,
            channels=channels,
            preview_meta=preview_meta,
        )
        return card

    def resolve_mobile_approval(
        self,
        payload: MobileApprovalDecisionPayload,
    ) -> ApprovalRelayReceipt:
        """Process mobile approval callback and resume or abort execution accordingly."""
        receipt = self._relay_engine.resolve_decision(payload)

        # Retrieve card to identify task
        card = self._relay_engine.get_active_card(payload.request_id)
        if not card:
            raise KeyError(f"Card for request {payload.request_id} missing")

        task_id = card.task_id
        if task_id in self._task_receipts:
            self._task_receipts[task_id].append(receipt)

        if receipt.is_expired:
            self._execution_phases[task_id] = HeadlessExecutionPhase.ABORTED
            return receipt

        if receipt.decision in (ApprovalDecisionKind.APPROVE, ApprovalDecisionKind.CONDITIONAL_ALLOW):
            self._execution_phases[task_id] = HeadlessExecutionPhase.RESUMED_ACTIVE
        else:
            self._execution_phases[task_id] = HeadlessExecutionPhase.ABORTED

        return receipt

    def complete_task(self, task_id: str) -> None:
        """Mark task as successfully completed."""
        if task_id not in self._execution_phases:
            raise KeyError(f"Task {task_id} not registered")
        self._execution_phases[task_id] = HeadlessExecutionPhase.COMPLETED

    def fail_task(self, task_id: str, error_message: str) -> None:
        """Mark task as failed with error log."""
        if task_id not in self._execution_phases:
            raise KeyError(f"Task {task_id} not registered")
        self.append_task_output(task_id, f"ERROR: {error_message}")
        self._execution_phases[task_id] = HeadlessExecutionPhase.FAILED

    def generate_reconnection_manifest(self, task_id: str) -> ReconnectionSyncManifest:
        """Generate full sync manifest upon desktop client reconnection."""
        if task_id not in self._execution_phases:
            raise KeyError(f"Task {task_id} not registered")

        now = time.time()
        detach_time = self._detach_timestamps.get(task_id, now)
        detached_duration = max(0.0, now - detach_time)
        detached_iso = datetime.fromtimestamp(detach_time, tz=timezone.utc).isoformat()
        reconnect_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        receipts = self._task_receipts.get(task_id, [])
        outputs = list(self._task_outputs.get(task_id, []))
        phase = self._execution_phases[task_id]

        # Reset attachment back to attached
        self._client_states[task_id] = ClientAttachmentState.ATTACHED

        resume_ready = phase in (
            HeadlessExecutionPhase.RUNNING_HEADLESS,
            HeadlessExecutionPhase.RESUMED_ACTIVE,
            HeadlessExecutionPhase.COMPLETED,
        )

        return ReconnectionSyncManifest(
            task_id=task_id,
            session_id=self._session_ids.get(task_id, ""),
            detached_at_iso=detached_iso,
            reconnected_at_iso=reconnect_iso,
            detached_duration_seconds=round(detached_duration, 2),
            execution_phase=phase,
            approval_events_count=len(receipts),
            receipts=receipts,
            incremental_output_lines=outputs,
            resume_ready=resume_ready,
        )

    def get_client_state(self, task_id: str) -> Optional[ClientAttachmentState]:
        """Fetch current client attachment state."""
        return self._client_states.get(task_id)

    def get_execution_phase(self, task_id: str) -> Optional[HeadlessExecutionPhase]:
        """Fetch current execution phase."""
        return self._execution_phases.get(task_id)
