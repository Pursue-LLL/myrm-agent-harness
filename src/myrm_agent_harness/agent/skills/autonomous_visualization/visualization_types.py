"""
[INPUT]
- User text queries, conversational context, or tabular datasets (CSV, JSON, dict)
- Optional configuration thresholds for intent detection

[OUTPUT]
- VisualizationCategory: Enum for target visual diagram/dashboard archetypes
- VisualizationIntentResult: Decision payload containing trigger status, category, confidence, and recommended visual format
- KpiMetric, ChartConfig, TableSpec: Normalized data structures for multi-dimensional dashboards
- DashboardSpec: Unified specification representing an autonomous interactive dashboard

[POS]
Domain types and data contracts for ZeroPromptAutonomousVisualizationAndDynamicWebDashboardEngine (Item 49 P1).
Maintains strict type hints, zero unstructured dict fallbacks, and frozen dataclasses for immutable safety.
"""

from dataclasses import dataclass, field
from enum import Enum


class VisualizationCategory(str, Enum):
    """Categorization of autonomous visualization intents."""

    TREND_LINE = "trend_line"           # Time series, growth trajectories, trends
    COMPARISON_BAR = "comparison_bar"   # Benchmarks, categorical comparisons, rankings
    PROPORTION_PIE = "proportion_pie"   # Market share, resource distribution, budget breakdown
    FUNNEL = "funnel"                   # Conversion stages, drop-off pipelines
    TOPOLOGY_GRAPH = "topology_graph"   # Architecture relationships, call graphs, networks
    DATA_DASHBOARD = "data_dashboard"   # Multi-table, multi-KPI comprehensive dynamic web board
    NONE = "none"                       # Pure narrative text, no visual structure needed


@dataclass(frozen=True)
class VisualizationIntentResult:
    """Detection decision for autonomous zero-prompt visualization invocation."""

    should_visualize: bool
    category: VisualizationCategory
    confidence: float
    matched_signals: list[str] = field(default_factory=list)
    recommended_title: str = ""
    suggested_renderer: str = "svg"  # "svg", "mermaid", "interactive_html"


@dataclass(frozen=True)
class KpiMetric:
    """Key Performance Indicator summary card metric."""

    label: str
    value: str
    change_pct: float | None = None
    trend: str = "neutral"  # "up", "down", "neutral"
    detail: str = ""


@dataclass(frozen=True)
class ChartSeries:
    """Individual data series in a chart."""

    name: str
    data: list[float]
    color: str | None = None


@dataclass(frozen=True)
class ChartConfig:
    """Visual chart configuration embedded in dynamic dashboard."""

    id: str
    title: str
    chart_type: str  # "line", "bar", "pie", "funnel"
    x_axis_labels: list[str] = field(default_factory=list)
    series: list[ChartSeries] = field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class TableSpec:
    """Tabular dataset view embedded in dynamic dashboard."""

    title: str
    headers: list[str]
    rows: list[list[str]]
    total_rows: int = 0


@dataclass(frozen=True)
class DashboardSpec:
    """Unified specification for an autonomous dynamic web dashboard."""

    title: str
    subtitle: str
    kpis: list[KpiMetric] = field(default_factory=list)
    charts: list[ChartConfig] = field(default_factory=list)
    tables: list[TableSpec] = field(default_factory=list)
    theme: str = "modern_dark"
    timestamp: float = 0.0
