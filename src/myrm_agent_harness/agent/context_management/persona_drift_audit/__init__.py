# [INPUT] drift_types, line_by_line_reconciler, purification_diff_engine, persona_drift_audit_suite
# [OUTPUT] Persona drift types, reconciler, diff engine, and DeterministicPersonaMemoryDriftAuditSuite facade
# [POS] Public API entry point for persona memory drift audit and line-by-line reconciliation

"""Deterministic persona memory drift audit and line-by-line reconciliation package."""

from .drift_types import (
    AuditLineSmell,
    BadSmellCategory,
    FileDriftAuditResult,
    PersonaFileKind,
    PurificationExecutionResult,
    ReconciliationDiffPlan,
)
from .line_by_line_reconciler import LineByLineRealityReconciler
from .persona_drift_audit_suite import (
    CANONICAL_PERSONA_FILE_SPECS,
    DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite,
    DeterministicPersonaMemoryDriftAuditSuite,
)
from .purification_diff_engine import PurificationDiffEngine

__all__ = [
    "AuditLineSmell",
    "BadSmellCategory",
    "CANONICAL_PERSONA_FILE_SPECS",
    "DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite",
    "DeterministicPersonaMemoryDriftAuditSuite",
    "FileDriftAuditResult",
    "LineByLineRealityReconciler",
    "PersonaFileKind",
    "PurificationDiffEngine",
    "PurificationExecutionResult",
    "ReconciliationDiffPlan",
]
