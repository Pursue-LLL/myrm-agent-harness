# checkpoint/

## Overview
Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's persistence capabilities,

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's p | ✅ |
| context_integration.py | Core | Integration module between browser checkpoint and Agent context. Provides utility functions for auto | ✅ |
| default_checkpointer.py | Core | Default checkpointer implementation. Provides an out-of-the-box SQLite checkpointer for development  | ✅ |
| hash_cache.py | Core | Hash cache module. Provides memory-safe LRU + TTL cache for tracking thread session hashes. | ✅ |
| incremental_checkpointer.py | Core | Checkpointer decorator. Wraps LangGraph checkpointer, tracks Session Vault hash in metadata for incr, and falls back to a fresh session when persisted state cannot be deserialized safely | ✅ |
| metadata.py | Core | Checkpoint metadata module. Defines browser task state stored in LangGraph checkpoint metadata, | ✅ |
| metrics.py | Core | Checkpoint monitoring metrics. Provides observability for checkpoint operations, supporting performa | ✅ |
| orchestrator.py | Core | Startup auto-recovery module. Scans incomplete checkpoints, rebuilds browser sessions, supports para | ✅ |
| protocols.py | Core | Browser checkpoint thread storage protocol. Defines unified interface for thread registration, updat | ✅ |
| session_state.py | Core | Browser session state tracking module. Provides utility functions for extracting and restoring brows | ✅ |
| thread_models.py | Core | Thread Registry data models. Defines thread record structures and database table schema. | ✅ |
| thread_registry.py | Core | Thread Registry storage layer. Operates on checkpoint_threads table, providing thread | ✅ |
