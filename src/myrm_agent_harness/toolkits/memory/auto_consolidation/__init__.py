"""Idle & Budget Gated Auto-Memory Consolidation Suite.

[INPUT]
- .models::{AutoMemoryGatingConfig, TurnGatingDecision, BudgetGatingDecision, IdleDetectionState, OverallGatingReport, SixDimensionalMemoryArtifact}
- .gating_engine::{calculate_information_density, estimate_consolidation_token_cost, evaluate_idle_status, evaluate_turn_and_info_gain, evaluate_budget_safety, evaluate_composite_gating}
- .six_dimensional_extractor::SixDimensionalMemoryExtractor
- .orchestrator::AutoMemoryConsolidationOrchestrator

[OUTPUT]
- Public exports of models, gating functions, extractor, and orchestrator.

[POS]
Harness package facade for Item 123 (IdleAndBudgetGatedAutoMemoryEngineSuite).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.auto_consolidation.gating_engine import (
    calculate_information_density,
    estimate_consolidation_token_cost,
    evaluate_budget_safety,
    evaluate_composite_gating,
    evaluate_idle_status,
    evaluate_turn_and_info_gain,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.models import (
    AutoMemoryGatingConfig,
    BudgetGatingDecision,
    IdleDetectionState,
    OverallGatingReport,
    SixDimensionalMemoryArtifact,
    TurnGatingDecision,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.orchestrator import (
    AutoMemoryConsolidationOrchestrator,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.six_dimensional_extractor import (
    SixDimensionalMemoryExtractor,
)

__all__ = [
    "AutoMemoryConsolidationOrchestrator",
    "AutoMemoryGatingConfig",
    "BudgetGatingDecision",
    "IdleDetectionState",
    "OverallGatingReport",
    "SixDimensionalMemoryArtifact",
    "SixDimensionalMemoryExtractor",
    "TurnGatingDecision",
    "calculate_information_density",
    "estimate_consolidation_token_cost",
    "evaluate_budget_safety",
    "evaluate_composite_gating",
    "evaluate_idle_status",
    "evaluate_turn_and_info_gain",
]
