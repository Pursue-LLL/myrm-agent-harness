"""
[INPUT]
- visualization_types.py
- intent_detector.py
- dashboard_compiler.py

[OUTPUT]
- Unified public exports for autonomous visualization and dynamic web dashboard engine

[POS]
Package facade for ZeroPromptAutonomousVisualizationAndDynamicWebDashboardEngine (Item 49 P1).
Strictly under 40 lines. Zero Any.
"""

from .dashboard_compiler import DataDashboardCompiler
from .intent_detector import VisualizationIntentDetector
from .visualization_types import (
    ChartConfig,
    ChartSeries,
    DashboardSpec,
    KpiMetric,
    TableSpec,
    VisualizationCategory,
    VisualizationIntentResult,
)

__all__ = [
    "ChartConfig",
    "ChartSeries",
    "DashboardSpec",
    "DataDashboardCompiler",
    "KpiMetric",
    "TableSpec",
    "VisualizationCategory",
    "VisualizationIntentDetector",
    "VisualizationIntentResult",
]
