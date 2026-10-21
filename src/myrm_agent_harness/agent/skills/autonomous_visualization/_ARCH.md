# autonomous_visualization/

## Overview
Autonomous Zero-Prompt Visualization & Dynamic Web Dashboard Engine (Item 49 P1).
Provides `VisualizationIntentDetector` to recognize analytical query patterns without explicit user commands, and `DataDashboardCompiler` to turn multi-table spreadsheet records into interactive standalone dashboards.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | Public exports for autonomous visualization engine. | — |
| `visualization_types.py` | Types | Domain models: VisualizationCategory, VisualizationIntentResult, DashboardSpec, KpiMetric, ChartConfig. | Yes |
| `intent_detector.py` | Engine | Heuristic detector for recognizing trend, comparison, funnel, and dashboard intents without explicit cues. | Yes |
| `dashboard_compiler.py` | Compiler | Transforms CSV and record tables into DashboardSpec and standalone interactive HTML artifacts. | Yes |
| `_ARCH.md` | Architecture | Architectural overview and module directory. | — |

## Key Dependencies
- Standard library: `csv`, `io`, `time`, `re`, `json`
