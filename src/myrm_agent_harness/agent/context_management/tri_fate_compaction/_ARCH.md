# tri_fate_compaction

Architecture and module inventory for the `tri_fate_compaction` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting tri-fate compaction models, decision marker, synthesizer, compactor, and facade suite |
| `tri_fate_types.py` | Domain models and contracts for turn-level tri-fate compaction and decoupled digest synthesis |
| `tri_fate_decision_marker.py` | Turn-level tri-fate decision marker arbitrating keep/summarize/drop destinies with safety gating |
| `decoupled_digest_synthesizer.py` | Decoupled digest synthesizer for distilling turns tagged with SUMMARIZE fate into structured context |
| `turn_level_tri_fate_compactor.py` | Turn-level tri-fate compactor orchestrating tripartite partitioning, decoupled synthesis, and assembly |
| `turn_level_tri_fate_compaction_suite.py` | Comprehensive facade suite for turn-level tri-fate compaction and decoupled digest synthesis |
