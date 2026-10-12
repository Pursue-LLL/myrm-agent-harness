# backends/

## Overview
Event log backends — built-in storage implementations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Event log backends — built-in storage implementations. | — |
| file_backend.py | Core | Built-in reference backend. Thread-safe via asyncio.Lock. Deduplicates appends by sequence within a run; `close()` ends the run and resets the watermark because a pooled backend serves consecutive runs whose sequences restart at 1. | ✅ |

## Key Dependencies

- `observability`
