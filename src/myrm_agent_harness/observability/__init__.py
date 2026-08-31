"""Observability module for Myrm Agent Harness

Provides monitoring and health inspection capabilities:
- Prometheus metrics (observability/metrics)
- Auth failure detection (observability/auth_detector)
- Health diagnostics and benchmarks (observability/diagnostics)
- Request tracing context and log correlation (observability/tracing)
- Runtime invariant assertions and registry (observability/invariants)
- Task friction telemetry and Eval Lab co-evolution (observability/friction)
- Skill compounding health evaluation (observability/digest)

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

[POS]
Observability tools for Myrm Agent framework. Provides passive metric collection,
active health probing, auth failure detection, request tracing context, runtime invariants, and friction telemetry.
"""

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
from .tracing import JsonFormatter, TracingContext, TracingLogFilter

__all__ = [
    "FrictionAggregator",
    "FrictionCategory",
    "FrictionExtractor",
    "FrictionSummary",
    "InvariantError",
    "InvariantMode",
    "InvariantSeverity",
    "InvariantViolation",
    "JsonFormatter",
    "RuntimeInvariantRegistry",
    "SkillCompoundingMetrics",
    "SkillHealthEvaluator",
    "SkillHealthScore",
    "SkillHealthStatus",
    "TaskFrictionEvent",
    "TracingContext",
    "TracingLogFilter",
    "default_invariant_registry",
    "detect_auth_failure",
    "friction_to_eval_case",
    "get_auth_error_hint",
]
