# online_economic_compact

Architecture and module inventory for the `online_economic_compact` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting economic compaction types, calculator, hook, continuation engine, and facade suite |
| `economic_compact_types.py` | Domain contracts, plan step models, decision results, configs, and continuation payloads |
| `compaction_economics_calculator.py` | Pure mathematical engine calculating breakeven horizons, combined carried debt, and compaction ROI |
| `subtask_boundary_hook.py` | Lifecycle event hook tracking plan steps and triggering economic compaction evaluations upon completion |
| `online_compact_continuation_engine.py` | State machine synthesizing milestone memos, updating savings ledgers, and bootstrapping new turns |
| `subtask_boundary_economic_compact_suite.py` | Central facade suite orchestrating subtask boundaries, economics evaluations, and new-turn continuity |
