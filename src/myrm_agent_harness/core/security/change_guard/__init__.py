"""ChangeGuard module for review decision lanes and evidence hardening (WS1-WS5).

[INPUT]
- HardenedFinding items, ChangeGuardException records, ChangeGuardPolicyConfig.

[OUTPUT]
- ChangeGuardEvaluationResult segregating Lane A gate verdicts from Lane B review questions.

[POS]
- Harness core security module preventing unverified authority changes.
"""

from __future__ import annotations

from .exceptions_manager import ChangeGuardExceptionsManager
from .guard import ChangeGuard, build_hardened_finding
from .lane_evaluator import ChangeGuardLaneEvaluator, get_highest_change_class
from .types import (
    CanonicalOutcome,
    ChangeClass,
    ChangeGuardEvaluationResult,
    ChangeGuardException,
    ChangeGuardPolicyConfig,
    DecisionLane,
    EvidenceRecord,
    EvidenceType,
    Gateability,
    HardenedFinding,
    LaneDecisionSummary,
    ProvenanceClass,
)

ChangeGuardEvaluator = ChangeGuard

__all__ = [
    "CanonicalOutcome",
    "ChangeClass",
    "ChangeGuard",
    "ChangeGuardEvaluationResult",
    "ChangeGuardEvaluator",
    "ChangeGuardException",
    "ChangeGuardExceptionsManager",
    "ChangeGuardLaneEvaluator",
    "ChangeGuardPolicyConfig",
    "DecisionLane",
    "EvidenceRecord",
    "EvidenceType",
    "Gateability",
    "HardenedFinding",
    "LaneDecisionSummary",
    "ProvenanceClass",
    "build_hardened_finding",
    "get_highest_change_class",
]
