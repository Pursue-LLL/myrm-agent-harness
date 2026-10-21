"""Planner-Generator-Evaluator Tri-Role Separation & Artifact Handoff Pipeline.

[INPUT]
- Domain types, pipeline coordinator, acceptance criteria, and manifest handoff protocols.

[OUTPUT]
- Unified public exports for Item 40 tri-role orchestration.

[POS]
- Harness coordination layer public module interface.
"""

from .pipeline_coordinator import TriRolePipelineCoordinator, TriRolePipelineError
from .types import (
    AcceptanceCriterion,
    ArtifactManifest,
    EvaluationVerdict,
    StageStatus,
    TriRolePipelineStage,
    TriRoleSessionState,
    TriRoleType,
)

__all__ = [
    "AcceptanceCriterion",
    "ArtifactManifest",
    "EvaluationVerdict",
    "StageStatus",
    "TriRolePipelineCoordinator",
    "TriRolePipelineError",
    "TriRolePipelineStage",
    "TriRoleSessionState",
    "TriRoleType",
]
