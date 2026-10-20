"""Clean Code Assembly Pipeline & Architecture Dependency Linter package (Item 62).

Exported symbols for 5-stage Clean Code multi-agent assembly and unidirectional layer enforcement.

[INPUT]
- __future__
- arch_dependency_linter
- pipeline_engine
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Clean Code Assembly Pipeline & Architecture Dependency Linter package (Item 62).
"""

from __future__ import annotations

from .arch_dependency_linter import DEFAULT_LAYER_RULES, ArchitectureDependencyLinter
from .pipeline_engine import STAGE_ORDER, CleanCodeAssemblyPipelineEngine
from .types import (
    ArchitectureViolation,
    CleanCodeTask,
    DependencyRule,
    LinterResult,
    PipelineStage,
    StageArtifact,
    StageStatus,
    ViolationType,
)

__all__ = [
    "ArchitectureDependencyLinter",
    "ArchitectureViolation",
    "CleanCodeAssemblyPipelineEngine",
    "CleanCodeTask",
    "DEFAULT_LAYER_RULES",
    "DependencyRule",
    "LinterResult",
    "PipelineStage",
    "STAGE_ORDER",
    "StageArtifact",
    "StageStatus",
    "ViolationType",
]
