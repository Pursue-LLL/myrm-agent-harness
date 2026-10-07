# Hierarchical Activity Compactor and Telemetry Pipeline Architecture

## 1. Positioning and Boundaries
The `activity_compactor` module in `myrm-agent-harness` provides desktop activity stream logging, multi-tier sliding window folding, milestone distillation, and telemetry, inspired by ChatGPT Desktop's Skysight module:

- **10-Minute Micro Window Folding**: Pure local algorithmic debouncing and window-title clustering (zero LLM calls, 0 token cost). Drops idle gaps and suppresses repetitive bursts.
- **6-Hour Macro Milestone Distillation**: Consolidates up to 36 micro slices into structured macro business milestones with dominant tools and categorization tags.
- **24-Hour Daily Preference Archive**: Synthesizes verified operational facts and long-term habits into persistent memory stores.
- **Compaction Telemetry**: Real-time tracking of raw events, micro/macro counts, idle events filtered, and estimated token savings (>90% reduction).
- **Single-Machine Sandbox**: Pure framework toolkit running locally inside the agent execution loop without multi-tenant baggage.

## 2. Component Structure
- `models.py`: Domain contracts and data schemas (`RawActivityEvent`, `MicroActivitySlice`, `MacroMilestoneFold`, `DailyPreferenceArchive`, `CompactorPipelineTelemetry`, `CompactorPipelineConfig`).
- `micro_folder.py`: 10-minute algorithmic deduplication and window debouncer (`MicroActivityFolder`).
- `macro_distiller.py`: 6-hour milestone aggregator and tag classifier (`MacroMilestoneDistiller`).
- `pipeline.py`: End-to-end pipeline coordinator and telemetry reporter (`HierarchicalActivityCompactorPipeline`).
- `__init__.py`: Clean exports for the toolkit.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Hierarchical time-window activity compactor and telemetry pipeline toolkit. | ✅ |
| `macro_distiller.py` | Core | Macro milestone distiller consolidating micro activity slices into 6-hour business folds. | ✅ |
| `micro_folder.py` | Core | Micro-window activity folder implementing algorithmic deduplication and debouncing. | ✅ |
| `models.py` | Types | Strongly-typed schemas for Hierarchical Time-Window Activity Compactor pipeline. | ✅ |
| `pipeline.py` | Core | Hierarchical activity compactor pipeline orchestrating 10min/6h/24h compaction tiers. | ✅ |
