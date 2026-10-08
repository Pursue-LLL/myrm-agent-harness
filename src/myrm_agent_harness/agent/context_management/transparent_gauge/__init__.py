"""Transparent context window gauge and 5-segment budget breakdown package facade.

[INPUT]
- None (package facade re-exporting gauge engine, types, and orchestration suite)

[OUTPUT]
- BudgetSegmentKind
- WatermarkAlertLevel
- BudgetSegmentBreakdown
- WatermarkState
- CompactionAdjustmentIntervention
- TransparentGaugeReceipt
- BudgetAnalyzer
- ContextWindowTransparentGaugeAndBudgetBreakdownSuite

[POS]
Transparent context window gauge and 5-segment budget breakdown package facade.
"""

from __future__ import annotations

from .budget_analyzer import BudgetAnalyzer
from .gauge_types import (
    BudgetSegmentBreakdown,
    BudgetSegmentKind,
    CompactionAdjustmentIntervention,
    TransparentGaugeReceipt,
    WatermarkAlertLevel,
    WatermarkState,
)
from .transparent_gauge_suite import ContextWindowTransparentGaugeAndBudgetBreakdownSuite

__all__ = [
    "BudgetSegmentKind",
    "WatermarkAlertLevel",
    "BudgetSegmentBreakdown",
    "WatermarkState",
    "CompactionAdjustmentIntervention",
    "TransparentGaugeReceipt",
    "BudgetAnalyzer",
    "ContextWindowTransparentGaugeAndBudgetBreakdownSuite",
]
