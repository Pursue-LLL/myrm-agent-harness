"""Data types and schemas for Sandbox Trust Transparency and Security Isolation Audit Card."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class IsolationLevel(StrEnum):
    """Categorization of sandbox runtime environment isolation boundary."""

    CLOUD_DEDICATED_SANDBOX = "cloud_dedicated_sandbox"
    LOCAL_RESTRICTED_CONTAINER = "local_restricted_container"
    HOST_DIRECT_FULL_TRUST = "host_direct_full_trust"


class TrustGrade(StrEnum):
    """Certification grade reflecting sandbox trust and containment confidence."""

    MAXIMUM_ISOLATION = "maximum_isolation"
    HIGH_ISOLATION = "high_isolation"
    RESTRICTED_SANDBOXED = "restricted_sandboxed"
    UNCONFINED_HOST = "unconfined_host"


class ProbeCheckStatus(StrEnum):
    """Status result of an individual health or containment probe check."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class ProbeCategory(StrEnum):
    """Security area probed by the self-audit probe."""

    FILESYSTEM = "filesystem"
    ENVIRONMENT = "environment"
    NETWORK = "network"
    CAPABILITIES = "capabilities"


@dataclass(frozen=True, slots=True)
class ProbeCheckItem:
    """Diagnostic check item evaluated during the sandbox self-audit scan."""

    check_id: str
    category: ProbeCategory
    description: str
    status: ProbeCheckStatus
    details: str


@dataclass(frozen=True, slots=True)
class SandboxTrustBadge:
    """Visual trust badge presented in UI status bars and client headers."""

    isolation_level: IsolationLevel
    trust_grade: TrustGrade
    trust_score: int
    summary: str
    badge_label: str
    color_hex: str


@dataclass(frozen=True, slots=True)
class SandboxHealthAuditReport:
    """Comprehensive health and container escape resistance diagnostic report."""

    report_id: str
    environment_id: str
    isolation_level: IsolationLevel
    checks: list[ProbeCheckItem]
    passed: bool
    score: int
    timestamp: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class PermissionBoundaryCard:
    """Interactive permission hot-boundary transparency card for users and auditors."""

    card_id: str
    environment_id: str
    isolation_level: IsolationLevel
    allowed_paths: list[str]
    denied_paths: list[str]
    egress_policy: str
    active_guards: list[str]
    generated_at: datetime = field(default_factory=_utc_now)
