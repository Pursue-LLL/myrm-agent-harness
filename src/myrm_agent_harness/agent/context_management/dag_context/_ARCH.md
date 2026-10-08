# dag_context

Architecture and module inventory for the `dag_context` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting DAG context models, folder, assertion engine, recall conduit, budget guard, and facade suite |
| `assertion_reconcile_engine.py` | Assertion reconciliation engine maintaining decision lifecycle and resolving overrides |
| `dag_context_suite.py` | Comprehensive facade suite for hierarchical DAG context, assertion reconciliation, and exact page recall |
| `dag_types.py` | Domain contracts and data models for hierarchical DAG context and assertion reconciliation |
| `exact_page_recall_conduit.py` | Exact page recall conduit enabling on-demand agent drill-down inspection of historical pages |
| `hierarchical_dag_folder.py` | Hierarchical DAG folder orchestrating multi-tier progressive summarization and lineage |
| `vram_performance_budget_guard.py` | VRAM hardware-aware performance budget guard locking active prompt to 6K-8K safety watermarks |
