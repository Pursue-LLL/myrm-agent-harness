"""Observability module for Myrm Agent Harness

Provides monitoring and health inspection capabilities:
- Prometheus metrics (observability/metrics)
- Auth failure detection (observability/auth_detector)
- Health diagnostics and benchmarks (observability/diagnostics)
- Request tracing context and log correlation (observability/tracing)
- Runtime invariant assertions and registry (observability/invariants)
- Skill compounding health evaluation (observability/digest)

[INPUT]
- Exception (POS: LLM call exceptions for auth detection)

[OUTPUT]
- Auth detection functions (detect_auth_failure, get_auth_error_hint)
- Metrics utilities (from observability/metrics)
- Diagnostics (from observability/diagnostics)
- Tracing primitives (TracingContext, TracingLogFilter, JsonFormatter)
- Invariant registry and types (from observability/invariants)
- Skill health evaluation (SkillHealthEvaluator, SkillCompoundingMetrics)

[POS]
Observability tools for Myrm Agent framework. Provides passive metric collection,
active health probing, auth failure detection, request tracing context, and runtime invariants.
"""

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
    "AuditSummaryStats",
    "AuditTrailEntry",
    "CompactionResult",
    "ComplianceOutcome",
    "ComplianceReport",
    "ComplianceTrailExporter",
    "DualTrackAuditCollector",
    "FleetQuotaItem",
    "FourTierSpendControlEngine",
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
    "TracingContext",
    "TracingLogFilter",
    "default_invariant_registry",
    "detect_auth_failure",
    "get_auth_error_hint",
]
