"""Observability module for Myrm Agent Harness

Provides monitoring and health inspection capabilities:
- Prometheus metrics (observability/metrics)
- Auth failure detection (observability/auth_detector)
- Health diagnostics and benchmarks (observability/diagnostics)
- Request tracing context and log correlation (observability/tracing)
- Runtime invariant assertions and registry (observability/invariants)
- Task friction telemetry and Eval Lab co-evolution (observability/friction)
- Skill compounding health evaluation (observability/digest)
- Auto-approval trigger diagnostics and dual-track attribution (observability/approval_audit)

[INPUT]
- Exception (POS: LLM call exceptions for auth detection)

[OUTPUT]
- Auth detection functions (detect_auth_failure, get_auth_error_hint)
- Metrics utilities (from observability/metrics)
- Diagnostics (from observability/diagnostics)
- Tracing primitives (TracingContext, TracingLogFilter, JsonFormatter)
- Invariant registry and types (from observability/invariants)
- Task friction telemetry (FrictionCategory, TaskFrictionEvent, FrictionAggregator)
- Skill health evaluation (SkillHealthEvaluator, SkillCompoundingMetrics)
- Auto-approval auditing (AutoApprovalAuditor, ApprovalTriggerCategory, AutoApprovalAuditReport)

[POS]
Observability tools for Myrm Agent framework. Provides passive metric collection,
active health probing, auth failure detection, request tracing context, runtime invariants, friction telemetry, and approval audit.
"""

from .approval_audit import (
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditor,
    AutoApprovalAuditReport,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
)
from .audit_trail import (
    AuditSummaryStats,
    AuditTrailEntry,
    ComplianceOutcome,
    ComplianceReport,
    ComplianceTrailExporter,
    DualTrackAuditCollector,
    PriorAuditState,
    RuleTriggerHit,
)
from .auth_detector import detect_auth_failure, get_auth_error_hint
from .digest import (
    SkillCompoundingMetrics,
    SkillHealthEvaluator,
    SkillHealthScore,
    SkillHealthStatus,
)
from .friction import (
    FrictionAggregator,
    FrictionCategory,
    FrictionExtractor,
    FrictionSummary,
    TaskFrictionEvent,
    friction_to_eval_case,
)
from .invariants import (
    InvariantError,
    InvariantMode,
    InvariantSeverity,
    InvariantViolation,
    RuntimeInvariantRegistry,
    default_invariant_registry,
)
from .spend_control import (
    FleetQuotaItem,
    FourTierSpendControlEngine,
    InterventionAction,
    SpendControlConfig,
    SpendInterventionDecision,
    SpendInterventionTier,
)
from .storage_governance import (
    CompactionResult,
    StateSnapshotManager,
    StateSnapshotMetadata,
    StateStorageCompactor,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceInspector,
    StorageGovernanceReport,
)
from .tracing import JsonFormatter, TracingContext, TracingLogFilter

__all__ = [
    "ApprovalTriggerCategory",
    "ApprovalTriggerEvent",
    "AuditSummaryStats",
    "AuditTrailEntry",
    "AutoApprovalAuditReport",
    "AutoApprovalAuditor",
    "CompactionResult",
    "ComplianceOutcome",
    "ComplianceReport",
    "ComplianceTrailExporter",
    "DualTrackAuditCollector",
    "DualTrackQuotaBreakdown",
    "FleetQuotaItem",
    "FourTierSpendControlEngine",
    "FrictionAggregator",
    "FrictionCategory",
    "FrictionExtractor",
    "FrictionSummary",
    "InterventionAction",
    "InvariantError",
    "InvariantMode",
    "InvariantSeverity",
    "InvariantViolation",
    "JsonFormatter",
    "PriorAuditState",
    "RuleTriggerHit",
    "RuntimeInvariantRegistry",
    "SkillCompoundingMetrics",
    "SkillHealthEvaluator",
    "SkillHealthScore",
    "SkillHealthStatus",
    "SpendControlConfig",
    "SpendInterventionDecision",
    "SpendInterventionTier",
    "StateSnapshotManager",
    "StateSnapshotMetadata",
    "StateStorageCompactor",
    "StorageCategory",
    "StorageCategoryBreakdown",
    "StorageGovernanceInspector",
    "StorageGovernanceReport",
    "TaskFrictionEvent",
    "TopOffenderItem",
    "TracingContext",
    "TracingLogFilter",
    "default_invariant_registry",
    "detect_auth_failure",
    "friction_to_eval_case",
    "get_auth_error_hint",
]
