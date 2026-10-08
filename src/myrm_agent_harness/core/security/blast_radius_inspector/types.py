"""Type definitions for Agent Action Surface Blast Radius Static Inspector and Guard Attribution Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActionSurfaceDimension(StrEnum):
    """Four core action surface dimensions under OWASP LLM06 Excessive Agency."""

    TOOLS = "TOOLS"  # Local/remote tool executions
    FILES = "FILES"  # Filesystem reads, writes, deletes, traversal
    APIS = "APIS"  # Outbound HTTP/REST/RPC endpoints
    SENDS = "SENDS"  # Irreversible outbound communications (email, posts, webhooks)


class AtomicActionCategory(StrEnum):
    """Eight canonical atomic action categories."""

    BROWSE = "BROWSE"  # Web/DOM inspection
    EMAIL = "EMAIL"  # Sending emails or messages
    POST = "POST"  # Publishing to public social/feeds
    SCHEDULE = "SCHEDULE"  # Cron/delayed execution
    APPROVE = "APPROVE"  # Triggering high-privilege approvals
    WRITE_FILE = "WRITE_FILE"  # Local disk write/overwrite
    TRIGGER_API = "TRIGGER_API"  # External service API invocation
    MUTATE_SYSTEM = "MUTATE_SYSTEM"  # Altering host/OS state or executing shell


class DangerTier(StrEnum):
    """Two-tier exposure risk stratification."""

    REACHABLE_VERIFIED = "REACHABLE_VERIFIED"  # Active path from untrusted ingress to critical sink
    INSTALL_LIABILITY = "INSTALL_LIABILITY"  # Inert in current config, live on install/extension activation


class GuardStatus(StrEnum):
    """Guard attribution status for a high-risk sink."""

    GUARD_ATTRIBUTED = "GUARD_ATTRIBUTED"  # Verified guardrails present (HITL, domain allowlist, path fence)
    UNGUARDED_CRITICAL = "UNGUARDED_CRITICAL"  # High-risk sink without active guardrails (excessive agency)


@dataclass(slots=True, frozen=True)
class SinkVulnerabilityItem:
    """Detected sink action item."""

    action_category: AtomicActionCategory
    dimension: ActionSurfaceDimension
    sink_identifier: str
    danger_tier: DangerTier
    description: str


@dataclass(slots=True, frozen=True)
class GuardAttributionItem:
    """Attribution of a sink to an existing or missing guardrail."""

    sink: SinkVulnerabilityItem
    guard_status: GuardStatus
    assigned_guard_name: str | None = None
    recommended_policy_fix: str | None = None


@dataclass(slots=True, frozen=True)
class ActionSurfaceExposureReport:
    """Comprehensive 4D action surface exposure metrics."""

    total_tools_count: int
    total_files_scope_count: int
    total_apis_count: int
    total_sends_count: int
    action_breakdown: dict[str, int] = field(default_factory=dict)
    reachable_verified_count: int = 0
    install_liability_count: int = 0
    unguarded_critical_count: int = 0
    exposure_score: float = 0.0  # 0.0 (safe) - 100.0 (high blast radius)
    pre_admission_allowed: bool = True
    admission_rejection_reason: str | None = None


@dataclass(slots=True, frozen=True)
class RepairPolicyPatch:
    """Synthesized least-privilege policy patch to remediate unguarded sinks."""

    patch_id: str
    target_sink: str
    injected_guard_type: str  # HITL, DOMAIN_ALLOWLIST, PATH_RESTRICTION
    patch_configuration: dict[str, str] = field(default_factory=dict)
    rationale: str = ""


@dataclass(slots=True, frozen=True)
class KillSwitchState:
    """Global emergency kill switch state."""

    is_engaged: bool
    engaged_at: float | None = None
    engaged_by: str | None = None
    reason: str | None = None
