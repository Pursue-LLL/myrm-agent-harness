# backends/

## Overview
Event log backends — built-in storage implementations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Event log backends — built-in storage implementations. | — |
| file_backend.py | Core | Built-in reference backend. Thread-safe via asyncio.Lock. Deduplicates appends by sequence within a run; `close()` ends the run and resets the watermark; `get_events()` implements fast line-level substring type pre-filtering and off-event-loop execution via `asyncio.to_thread`; `remove_session_log()` deletes one session's file on demand (rejects ids resolving outside the log directory) and resets the dedup watermark when it removes the backend's own session. | ✅ |

## Key Dependencies

- `observability`
