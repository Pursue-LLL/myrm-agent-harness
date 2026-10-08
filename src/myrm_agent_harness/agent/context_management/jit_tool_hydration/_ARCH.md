# jit_tool_hydration

Architecture and module inventory for the `jit_tool_hydration` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting JIT tool hydration types, catalog indexer, hydration engine, dehydrator, and facade suite |
| `hydration_types.py` | Domain models and contracts for low-context friendly JIT tool hydration and virtual catalog |
| `virtual_tool_catalog_indexer.py` | Virtual tool catalog indexer producing ultra-compact prompt-cache friendly tool summaries |
| `jit_schema_hydration_engine.py` | Just-in-time tool schema hydration engine matching intents and mounting schemas on demand |
| `post_execution_tool_dehydrator.py` | Post-execution tool dehydrator and schema garbage collector |
| `low_context_jit_tool_hydration_suite.py` | Unified facade suite coordinating virtual catalog indexing, intent-driven JIT hydration, and post-turn schema reclamation |
