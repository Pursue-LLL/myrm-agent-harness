# concurrency/

## Overview
Async coordination primitives for framework infrastructure that needs bounded parallel execution and serialized state merges.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports concurrency primitives. | ✅ |
| limiter.py | Core | Async context manager that bounds concurrent work with an `asyncio.Semaphore`. | ✅ |
| reducer.py | Core | Async-safe state reducer that serializes patch application behind an `asyncio.Lock`. | ✅ |

## Key Dependencies

- `asyncio`
