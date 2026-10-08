"""
[POS] src/myrm_agent_harness/core/security/system_app_boundary/facade.py
[INPUT] time, uuid, types, boundary_checker, write_consent_gate
[OUTPUT] SystemAppBoundaryFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
import uuid

from .boundary_checker import SystemAppBoundaryChecker
from .types import (
    AppAccessRequest,
    AppAccessVerdict,
    BoundaryGateDecision,
    SystemAppAuditRecord,
    SystemAppBoundaryMetrics,
    SystemAppScopeRule,
    SystemAppType,
)
from .write_consent_gate import WriteConsentGate


class SystemAppBoundaryFacade:
    """Unified entrypoint for system app privacy boundary enforcement and write consent gate."""

    def __init__(
        self,
        checker: SystemAppBoundaryChecker | None = None,
        consent_gate: WriteConsentGate | None = None,
    ) -> None:
        self._checker = checker or SystemAppBoundaryChecker()
        self._consent_gate = consent_gate or WriteConsentGate()
        self._metrics = SystemAppBoundaryMetrics()
        self._audit_log: list[SystemAppAuditRecord] = []

    @property
    def metrics(self) -> SystemAppBoundaryMetrics:
        """Shared operational telemetry counters."""
        return self._metrics

    def set_scope_rule(self, rule: SystemAppScopeRule) -> None:
        """Set container access boundary and consent policy for an application."""
        self._checker.set_scope_rule(rule)

    def get_scope_rule(self, app_type: SystemAppType) -> SystemAppScopeRule:
        """Fetch active scoping boundary rule for application."""
        return self._checker.get_scope_rule(app_type)

    def lockdown_app(self, app_type: SystemAppType) -> None:
        """Lock down target system app, denying all access immediately."""
        self._checker.lockdown_app(app_type)

    def unlock_app(self, app_type: SystemAppType) -> None:
        """Release emergency lockdown on system application."""
        self._checker.unlock_app(app_type)

    def evaluate_access(self, request: AppAccessRequest) -> AppAccessVerdict:
        """Evaluate an application access or mutation attempt."""
        self._metrics.requests_evaluated_total += 1
        decision, reason = self._checker.evaluate_request(request)

        audit_id = f"aud-{uuid.uuid4().hex[:12]}"
        is_allowed = decision == BoundaryGateDecision.PERMITTED_SILENT

        if decision == BoundaryGateDecision.PERMITTED_SILENT:
            self._metrics.silent_reads_permitted_total += 1
        elif decision == BoundaryGateDecision.REQUIRE_WRITE_CONSENT:
            self._metrics.write_consents_requested_total += 1
            self._consent_gate.enqueue_for_consent(request)
        elif decision == BoundaryGateDecision.BOUNDARY_VIOLATION_BLOCKED:
            self._metrics.boundary_violations_blocked_total += 1
        elif decision == BoundaryGateDecision.EMERGENCY_APP_LOCKED:
            self._metrics.lockdown_blocked_total += 1

        self._record_audit(
            audit_id=audit_id,
            request=request,
            is_allowed=is_allowed,
            reason=reason,
        )

        return AppAccessVerdict(
            request_id=request.request_id,
            decision=decision,
            is_allowed=is_allowed,
            diagnostic_reason=reason,
            audit_id=audit_id,
        )

    def grant_write_consent(
        self, request_id: str, approver_note: str = "Authorized by User"
    ) -> AppAccessVerdict | None:
        """Grant explicit human authorization for a held write operation."""
        req = self._consent_gate.grant_consent(request_id, approver_note)
        if req is None:
            return None

        self._metrics.write_consents_granted_total += 1
        audit_id = f"aud-{uuid.uuid4().hex[:12]}"
        reason = f"Write consent explicitly granted by user: {approver_note}"

        self._record_audit(
            audit_id=audit_id,
            request=req,
            is_allowed=True,
            reason=reason,
        )

        return AppAccessVerdict(
            request_id=req.request_id,
            decision=BoundaryGateDecision.PERMITTED_SILENT,
            is_allowed=True,
            diagnostic_reason=reason,
            audit_id=audit_id,
        )

    def reject_write_consent(
        self, request_id: str, reason: str = "Rejected by User"
    ) -> bool:
        """Reject and drop a held write operation."""
        req = self._consent_gate.get_pending_request(request_id)
        if req is not None:
            audit_id = f"aud-{uuid.uuid4().hex[:12]}"
            self._record_audit(
                audit_id=audit_id,
                request=req,
                is_allowed=False,
                reason=f"Write consent rejected: {reason}",
            )
        return self._consent_gate.reject_consent(request_id, reason)

    def list_pending_consents(self) -> tuple[AppAccessRequest, ...]:
        """List all write requests currently awaiting human consent."""
        return self._consent_gate.list_pending_consents()

    def get_audit_trail(self, limit: int = 50) -> tuple[SystemAppAuditRecord, ...]:
        """Fetch recent access audit trail records."""
        return tuple(self._audit_log[-limit:])

    def _record_audit(
        self,
        audit_id: str,
        request: AppAccessRequest,
        is_allowed: bool,
        reason: str,
    ) -> None:
        record = SystemAppAuditRecord(
            audit_id=audit_id,
            timestamp_epoch=time.time(),
            request_id=request.request_id,
            session_id=request.session_id,
            app_type=request.app_type,
            operation_type=request.operation_type,
            target_container=request.target_container,
            is_allowed=is_allowed,
            reason=reason,
        )
        self._audit_log.append(record)
