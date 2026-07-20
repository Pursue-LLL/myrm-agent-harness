# incremental/

## Overview
Incremental state tracking for monitoring data changes.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Incremental state tracking for monitoring data changes. | — |
| manager.py | Core | Incremental monitor lifecycle manager. | ✅ |
| protocols.py | Core | Protocol for incremental monitoring. | ✅ |
| hash_monitor.py | Core | Hash-based monitor with JSON canonicalization for stable deltas. | ✅ |
| set_monitor.py | Core | Set-based incremental monitor. | ✅ |
| types.py | Config | Domain types for incremental monitoring. | ✅ |

## Key Dependencies

- `toolkits`
