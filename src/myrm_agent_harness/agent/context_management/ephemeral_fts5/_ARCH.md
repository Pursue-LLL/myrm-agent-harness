# ephemeral_fts5

Architecture and module inventory for the `ephemeral_fts5` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting ephemeral FTS5 contracts, chunker, vault, retriever, and facade suite |
| `ephemeral_fts5_types.py` | Domain models, configs, receipts, and search items for session FTS5 vault |
| `markdown_code_block_chunker.py` | Markdown structure-aware chunker preserving heading paths and code block fence integrity |
| `ephemeral_sqlite_fts5_vault.py` | Ephemeral SQLite FTS5 session-isolated knowledge vault managing dual Porter and Trigram virtual tables |
| `dual_strategy_rrf_retriever.py` | Dual-strategy Porter and Trigram matcher with Reciprocal Rank Fusion (RRF) ranking |
| `batch_queries_coalescing_gate.py` | Batch queries coalescing gate executing all session lookups in a single round |
| `ephemeral_session_fts5_suite.py` | End-to-end facade orchestrating ephemeral session FTS5 vault indexing and batch retrieval |
