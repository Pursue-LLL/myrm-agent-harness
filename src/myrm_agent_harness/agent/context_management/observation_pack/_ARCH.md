# observation_pack

Architecture and module inventory for the `observation_pack` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting ObservationPack types, store, pipeline, tool, and facade suite |
| `observation_pack_types.py` | Domain types, handles, page models, configs, and batch transformation records |
| `content_addressed_store.py` | Cryptographic SHA-256 content-addressed store offering immutable archival and paged slicing |
| `observation_degradation_pipeline.py` | Sliding-window degradation pipeline enforcing 2-turn full sends and excerpt placeholders |
| `observation_recall_tool.py` | Native meta-tool providing on-demand paged recall for archived observations |
| `observation_pack_suite.py` | Unified facade suite orchestrating storage, sliding windows, and paged retrieval |
