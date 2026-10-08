# hybrid_engine/

## Overview

Orchestrates zero-config SQLite FTS5, offline synonym expansion,.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | ZeroConfigDualDriveHybridMemoryAndGracefulDegradationSuite. | ✅ |
| `circuit_breaker.py` | Core | Lightweight thread-safe circuit breaker for embedding providers. | ✅ |
| `dual_drive_engine.py` | Core | Orchestrates zero-config SQLite FTS5, offline synonym expansion, adaptive RRF, and circuit breaker. | ✅ |
| `models.py` | Types | Types and models for hybrid engine. | ✅ |
| `reranker.py` | Core | Adaptive Reciprocal Rank Fusion reranker with recency decay and importance weighting. | ✅ |
| `sqlite_fts5_store.py` | Core | Embedded SQLite FTS5 storage and retrieval engine. | ✅ |
| `synonym_expander.py` | Core | Zero-dependency, offline semantic synonym expansion engine. | ✅ |
