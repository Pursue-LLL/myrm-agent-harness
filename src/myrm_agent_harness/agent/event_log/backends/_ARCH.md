# backends/

## Overview
Event log backends — built-in storage implementations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Event log backends — built-in storage implementations. | — |
| file_backend.py | Core | Built-in reference backend. Thread-safe via asyncio.Lock. Deduplicates appends by sequence within a run; `close()` ends the run and resets the watermark because a pooled backend serves consecutive runs whose sequences restart at 1; `remove_session_log()` deletes one session's file on demand (rejects ids resolving outside the log directory) and resets the dedup watermark when it removes the backend's own session. | ✅ |

## Key Dependencies

- `observability`
