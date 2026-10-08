# [INPUT]: None
# [OUTPUT]: CompactionDecisionResult, CompactionEconomicsCalculator, CompactionEconomicsConfig, ContinuationTurnPayload, EconomicCompactionLedger, OnlineCompactContinuationEngine, PlanStep, PlanStepStatus, SubtaskBoundaryHook, SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite
# [POS]: agent/context_management/online_economic_compact/__init__.py

"""Online context compaction at subtask boundaries with economic breakeven models.

[INPUT]
- None (Public package entrypoint).

[OUTPUT]
- CompactionDecisionResult: Mathematical verdict on compaction ROI.
- CompactionEconomicsCalculator: Pure mathematical breakeven engine.
- CompactionEconomicsConfig: Threshold and safety multiplier configuration.
- ContinuationTurnPayload: Package containing memo summary and continuation state for the new turn.
- EconomicCompactionLedger: Carried debt and lifetime savings accounting ledger.
- OnlineCompactContinuationEngine: Post-compaction state transition and prompt bootstrap engine.
- PlanStep: Typed subtask representation.
- PlanStepStatus: Execution lifecycle enum.
- SubtaskBoundaryHook: Event hook evaluating completed plan steps.
- SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite: Central facade suite.

[POS]
Package facade for NVIDIA SoL-Pi inspired online context compaction and economics.
"""

from __future__ import annotations

from .compaction_economics_calculator import CompactionEconomicsCalculator
from .economic_compact_types import (
    CompactionDecisionResult,
    CompactionEconomicsConfig,
    ContinuationTurnPayload,
    EconomicCompactionLedger,
    PlanStep,
    PlanStepStatus,
)
from .online_compact_continuation_engine import OnlineCompactContinuationEngine
from .subtask_boundary_economic_compact_suite import (
    SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite,
)
from .subtask_boundary_hook import SubtaskBoundaryHook

__all__ = [
    "CompactionDecisionResult",
    "CompactionEconomicsCalculator",
    "CompactionEconomicsConfig",
    "ContinuationTurnPayload",
    "EconomicCompactionLedger",
    "OnlineCompactContinuationEngine",
    "PlanStep",
    "PlanStepStatus",
    "SubtaskBoundaryHook",
    "SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite",
]
