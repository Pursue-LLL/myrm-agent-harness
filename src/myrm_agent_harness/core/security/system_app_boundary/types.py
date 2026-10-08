"""
[POS] src/myrm_agent_harness/core/security/system_app_boundary/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] SystemAppType, AppOperationType, BoundaryGateDecision, SystemAppScopeRule, AppAccessRequest, AppAccessVerdict, SystemAppAuditRecord, SystemAppBoundaryMetrics
Domain types for Local System App Privacy Boundary & Write Consent Gate Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SystemAppType(StrEnum):
    """Local first-party and system application categories."""

    MAIL = "MAIL"
    NOTES = "NOTES"
    PHOTOS = "PHOTOS"
    CALENDAR = "CALENDAR"
    CONTACTS = "CONTACTS"
    REMINDERS = "REMINDERS"
    OTHER = "OTHER"


class AppOperationType(StrEnum):
    """Nature of application operation differentiating read-only from state mutation."""

    READ_ONLY = "READ_ONLY"
    MUTATE_WRITE = "MUTATE_WRITE"
    DELETE_PURGE = "DELETE_PURGE"


class BoundaryGateDecision(StrEnum):
    """Authorization decisions rendered by system app boundary and write consent gate."""

    PERMITTED_SILENT = "PERMITTED_SILENT"
    REQUIRE_WRITE_CONSENT = "REQUIRE_WRITE_CONSENT"
    BOUNDARY_VIOLATION_BLOCKED = "BOUNDARY_VIOLATION_BLOCKED"
    EMERGENCY_APP_LOCKED = "EMERGENCY_APP_LOCKED"


@dataclass(frozen=True)
class SystemAppScopeRule:
    """Declared scope boundary defining permitted containers and write policies for an app."""

    app_type: SystemAppType
    allowed_containers: tuple[str, ...] = ()
    allow_mutations_without_prompt: bool = False
    is_locked_down: bool = False


@dataclass(frozen=True)
class AppAccessRequest:
    """Request payload submitted when agent attempts to interact with a system application."""

    request_id: str
    session_id: str
    app_type: SystemAppType
    operation_type: AppOperationType
    target_container: str
    payload_summary: str
    is_external_tainted: bool = False


@dataclass(frozen=True)
class AppAccessVerdict:
    """Evaluation verdict governing access to local system app."""

    request_id: str
    decision: BoundaryGateDecision
    is_allowed: bool
    diagnostic_reason: str
    audit_id: str


@dataclass(frozen=True)
class SystemAppAuditRecord:
    """Tamper-evident audit record logging local application access attempts."""

    audit_id: str
    timestamp_epoch: float
    request_id: str
    session_id: str
    app_type: SystemAppType
    operation_type: AppOperationType
    target_container: str
    is_allowed: bool
    reason: str


@dataclass
class SystemAppBoundaryMetrics:
    """Cumulative telemetry metrics for local system app boundary access."""

    requests_evaluated_total: int = 0
    silent_reads_permitted_total: int = 0
    write_consents_requested_total: int = 0
    write_consents_granted_total: int = 0
    boundary_violations_blocked_total: int = 0
    lockdown_blocked_total: int = 0
