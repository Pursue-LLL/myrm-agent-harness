"""Procedural Memory and Engineering Workflow Governance Engine.

Provides human intervention safety rule distillation, vertical domain engineering
procedural rule management, deterministic preflight DRC assertion gates, and
automated parameter remediation.
"""

from .engine import (
    DomainEngineeringProceduralEngine,
    EngineeringPreflightViolationError,
)
from .evaluator import EngineeringRuleCompilerAndEvaluator
from .extractor import InterventionMemoryExtractor
from .injector import ProceduralRuleInjector
from .models import (
    ConstraintBoundary,
    EngineeringProceduralRule,
    EngineeringRuleSeverity,
    HumanInterventionEvent,
    InterventionType,
    PreflightCheckReport,
    ProceduralRule,
    RuleDistillationResult,
    RuleEvaluationResult,
    RuleInjectionContext,
    RuleScope,
)

__all__ = [
    "ConstraintBoundary",
    "DomainEngineeringProceduralEngine",
    "EngineeringPreflightViolationError",
    "EngineeringProceduralRule",
    "EngineeringRuleCompilerAndEvaluator",
    "EngineeringRuleSeverity",
    "HumanInterventionEvent",
    "InterventionMemoryExtractor",
    "InterventionType",
    "PreflightCheckReport",
    "ProceduralRule",
    "ProceduralRuleInjector",
    "RuleDistillationResult",
    "RuleEvaluationResult",
    "RuleInjectionContext",
    "RuleScope",
]
