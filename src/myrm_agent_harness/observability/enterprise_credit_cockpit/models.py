"""[INPUT] Enterprise credit pool quotas, risk classifications, and audit signals.
[OUTPUT] Immutable data structures for enterprise credit ops and actor-time-data-risk audit trails.
[POS] myrm_agent_harness.observability.enterprise_credit_cockpit.models

Defines the core data models for the Enterprise Credit and Risk Ops Cockpit,
binding resource credit consumption with actor identity, timestamp, accessed data scope,
and security risk verdicts in a unified auditable chain.
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class RiskLevel(str, Enum):
    """Categorized security risk severity level."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskBehaviorType(str, Enum):
    """Categorized security behavior or policy event."""

    NONE = "NONE"
    PII_LEAK_PREVENTED = "PII_LEAK_PREVENTED"
    SENSITIVE_DATA_EXPORT = "SENSITIVE_DATA_EXPORT"
    PROMPT_INJECTION_ATTEMPT = "PROMPT_INJECTION_ATTEMPT"
    RATE_SPIKE = "RATE_SPIKE"
    UNAUTHORIZED_DATA_ACCESS = "UNAUTHORIZED_DATA_ACCESS"


class PolicyVerdict(str, Enum):
    """Governance action taken on the operation."""

    ALLOW = "ALLOW"
    AUDIT = "AUDIT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CreditRiskAuditRecord:
    """Unified audit trail record binding Actor, Time, Data Scope, and Risk Behavior."""

    record_id: str
    actor_id: str
    product_surface: str
    interaction_summary: str
    data_object_scope: str
    credit_consumed: float
    risk_level: RiskLevel
    risk_behavior: RiskBehaviorType
    policy_verdict: PolicyVerdict
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | float | int]:
        """Convert record to JSON-serializable dictionary."""
        return {
            "record_id": self.record_id,
            "actor_id": self.actor_id,
            "product_surface": self.product_surface,
            "interaction_summary": self.interaction_summary,
            "data_object_scope": self.data_object_scope,
            "credit_consumed": self.credit_consumed,
            "risk_level": self.risk_level.value,
            "risk_behavior": self.risk_behavior.value,
            "policy_verdict": self.policy_verdict.value,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class CreditPoolAllocation:
    """Allocation status per product surface."""

    surface_name: str
    credit_spent: float
    request_count: int

    def to_dict(self) -> dict[str, str | float | int]:
        return {
            "surface_name": self.surface_name,
            "credit_spent": self.credit_spent,
            "request_count": self.request_count,
        }


@dataclass(frozen=True)
class EnterpriseCockpitSnapshot:
    """Aggregated cockpit overview for enterprise credit and risk governance."""

    total_credit_quota: float
    total_credit_spent: float
    available_credit: float
    utilization_pct: float
    is_quota_breached: bool
    warning_threshold_pct: float
    total_audit_records: int
    risk_event_count: int
    blocked_count: int
    allocations_by_surface: tuple[CreditPoolAllocation, ...] = field(default_factory=tuple)
    recent_audit_records: tuple[CreditRiskAuditRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, float | bool | int | list[dict[str, str | float | int]]]:
        return {
            "total_credit_quota": self.total_credit_quota,
            "total_credit_spent": self.total_credit_spent,
            "available_credit": self.available_credit,
            "utilization_pct": self.utilization_pct,
            "is_quota_breached": self.is_quota_breached,
            "warning_threshold_pct": self.warning_threshold_pct,
            "total_audit_records": self.total_audit_records,
            "risk_event_count": self.risk_event_count,
            "blocked_count": self.blocked_count,
            "allocations_by_surface": [a.to_dict() for a in self.allocations_by_surface],
            "recent_audit_records": [r.to_dict() for r in self.recent_audit_records],
        }
