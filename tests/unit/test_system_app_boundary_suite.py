"""
[POS] tests/unit/test_system_app_boundary_suite.py
[INPUT] myrm_agent_harness.core.security.system_app_boundary
[OUTPUT] Unit tests for SystemAppBoundaryFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.system_app_boundary import (
    AppAccessRequest,
    AppOperationType,
    BoundaryGateDecision,
    SystemAppBoundaryFacade,
    SystemAppScopeRule,
    SystemAppType,
)


def test_read_access_within_and_outside_boundary() -> None:
    """Test read-only scoping: permit within declared folder and block outside container boundary."""
    facade = SystemAppBoundaryFacade()
    facade.set_scope_rule(
        SystemAppScopeRule(
            app_type=SystemAppType.NOTES,
            allowed_containers=("AI Work", "Projects"),
        )
    )

    # 1. Access within allowed container
    req_allowed = AppAccessRequest(
        request_id="req-01",
        session_id="sess-01",
        app_type=SystemAppType.NOTES,
        operation_type=AppOperationType.READ_ONLY,
        target_container="AI Work",
        payload_summary="List recent notes in AI Work folder",
    )
    v1 = facade.evaluate_access(req_allowed)
    assert v1.decision == BoundaryGateDecision.PERMITTED_SILENT
    assert v1.is_allowed is True

    # 2. Access outside declared container (e.g. personal diary)
    req_blocked = AppAccessRequest(
        request_id="req-02",
        session_id="sess-01",
        app_type=SystemAppType.NOTES,
        operation_type=AppOperationType.READ_ONLY,
        target_container="Personal Diary",
        payload_summary="Scan private diary notes",
    )
    v2 = facade.evaluate_access(req_blocked)
    assert v2.decision == BoundaryGateDecision.BOUNDARY_VIOLATION_BLOCKED
    assert v2.is_allowed is False


def test_write_access_requires_consent_and_approval() -> None:
    """Test mutation requiring human consent and subsequent explicit approval workflow."""
    facade = SystemAppBoundaryFacade()
    facade.set_scope_rule(
        SystemAppScopeRule(
            app_type=SystemAppType.MAIL,
            allowed_containers=("Work", "Outbox"),
            allow_mutations_without_prompt=False,
        )
    )

    # Mutation attempt on Mail
    write_req = AppAccessRequest(
        request_id="req-write-01",
        session_id="sess-02",
        app_type=SystemAppType.MAIL,
        operation_type=AppOperationType.MUTATE_WRITE,
        target_container="Work",
        payload_summary="Send email to team@company.com with report",
    )
    v_held = facade.evaluate_access(write_req)
    assert v_held.decision == BoundaryGateDecision.REQUIRE_WRITE_CONSENT
    assert v_held.is_allowed is False

    pending = facade.list_pending_consents()
    assert len(pending) == 1
    assert pending[0].request_id == "req-write-01"

    # User explicitly grants consent
    v_approved = facade.grant_write_consent(
        "req-write-01", approver_note="User reviewed recipient and body"
    )
    assert v_approved is not None
    assert v_approved.decision == BoundaryGateDecision.PERMITTED_SILENT
    assert v_approved.is_allowed is True
    assert len(facade.list_pending_consents()) == 0


def test_write_rejection_and_external_tainted_enforcement() -> None:
    """Test rejection and tainted external context strictly forcing consent even if unprompted mutation enabled."""
    facade = SystemAppBoundaryFacade()
    # Configure unprompted mutation allowed for internal tasks
    facade.set_scope_rule(
        SystemAppScopeRule(
            app_type=SystemAppType.REMINDERS,
            allowed_containers=("Sprint Tasks",),
            allow_mutations_without_prompt=True,
        )
    )

    # 1. Clean internal mutation -> permitted silently
    clean_req = AppAccessRequest(
        request_id="req-clean",
        session_id="sess-03",
        app_type=SystemAppType.REMINDERS,
        operation_type=AppOperationType.MUTATE_WRITE,
        target_container="Sprint Tasks",
        payload_summary="Add todo item",
        is_external_tainted=False,
    )
    v_clean = facade.evaluate_access(clean_req)
    assert v_clean.decision == BoundaryGateDecision.PERMITTED_SILENT
    assert v_clean.is_allowed is True

    # 2. External tainted request -> MUST require consent regardless of unprompted flag
    tainted_req = AppAccessRequest(
        request_id="req-tainted",
        session_id="sess-03",
        app_type=SystemAppType.REMINDERS,
        operation_type=AppOperationType.MUTATE_WRITE,
        target_container="Sprint Tasks",
        payload_summary="Injected reminder from phishing email",
        is_external_tainted=True,
    )
    v_tainted = facade.evaluate_access(tainted_req)
    assert v_tainted.decision == BoundaryGateDecision.REQUIRE_WRITE_CONSENT
    assert v_tainted.is_allowed is False

    # Reject consent
    assert facade.reject_write_consent("req-tainted", reason="Suspicious injection") is True
    assert len(facade.list_pending_consents()) == 0


def test_emergency_lockdown_blocks_all_operations() -> None:
    """Test emergency app lockdown physically refusing all access attempts."""
    facade = SystemAppBoundaryFacade()
    facade.set_scope_rule(
        SystemAppScopeRule(
            app_type=SystemAppType.PHOTOS,
            allowed_containers=("Public Album",),
        )
    )

    facade.lockdown_app(SystemAppType.PHOTOS)

    req = AppAccessRequest(
        request_id="req-lockdown",
        session_id="sess-04",
        app_type=SystemAppType.PHOTOS,
        operation_type=AppOperationType.READ_ONLY,
        target_container="Public Album",
        payload_summary="Scan photos",
    )
    v_locked = facade.evaluate_access(req)
    assert v_locked.decision == BoundaryGateDecision.EMERGENCY_APP_LOCKED
    assert v_locked.is_allowed is False

    # Unlock restores access
    facade.unlock_app(SystemAppType.PHOTOS)
    v_restored = facade.evaluate_access(req)
    assert v_restored.decision == BoundaryGateDecision.PERMITTED_SILENT
    assert v_restored.is_allowed is True


def test_audit_trail_and_metrics() -> None:
    """Test comprehensive audit logging and metric counters."""
    facade = SystemAppBoundaryFacade()
    facade.evaluate_access(
        AppAccessRequest(
            request_id="req-aud-01",
            session_id="sess-05",
            app_type=SystemAppType.CALENDAR,
            operation_type=AppOperationType.READ_ONLY,
            target_container="Work",
            payload_summary="Check calendar meetings",
        )
    )

    trail = facade.get_audit_trail()
    assert len(trail) >= 1
    assert trail[-1].app_type == SystemAppType.CALENDAR

    m = facade.metrics
    assert m.requests_evaluated_total >= 1
    assert m.silent_reads_permitted_total >= 1
