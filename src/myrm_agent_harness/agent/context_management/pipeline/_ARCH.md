# pipeline/

## Overview
Pipeline module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Pipeline module. | — |
| base.py | Core | Pipeline processor base class. Defines the processor interface (BaseProcessor) and context data stru | ✅ |
| engine.py | Core | Pipeline engine. Serializes chat-scoped context mutations with the session lock, then runs processors sequentially with per-processor failure isolation. | ✅ |

| Submodule | Description |
|-----------|-------------|
| processors/ | Pipeline processors for filtering, cache-TTL pruning, pre-compaction recall, compression, session notes, summarization, normalization, and explicit cache-control markers. |

## Key Dependencies

- `utils`
- `infra/session_lock.py`
