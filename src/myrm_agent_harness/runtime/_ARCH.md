# runtime/

## Overview
Agent runtime infrastructure for single-instance execution.

Detailed design: [CONVERSATION_FORK_DESIGN.md](CONVERSATION_FORK_DESIGN.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent runtime infrastructure for single-instance execution. | — |
| artifact_judge.py | Core | Artifact identification system. | ✅ |
| checkpoint_protocols.py | Core | Protocol definition for checkpointer objects. | ✅ |
| compression.py | Core | Generic file compression utilities for storage optimization. | ✅ |
| doctor.py | Core | Concurrent diagnostic engine. Async-parallel model with lightweight HTTP probe, deploy mode awareness, and structured diagnostics. | ✅ |
| doctor_cli.py | Core | CLI Formatter for Myrm Doctor. | ✅ |
| execution_paths.py | Core | Unified execution path constants and utilities, including content-addressed context archive metadata, restore-map sidecar paths, and archive sidecar path candidate normalization. | ✅ |
| fork_types.py | Config | Defines data structures for conversation forking feature. Used by business layer | ✅ |
| memory_pressure.py | Core | Global memory pressure coordination. Framework provides the monitor and hooks; | ✅ |
| resource_monitor.py | Core | High-fidelity resource monitor with history sampling, adaptive heap profiling, and production-visible [MEMORY] INFO logging. | ✅ |
| startup.py | Core | Optional toolkit for monitoring application startup performance. | ✅ |

| Submodule | Description |
|-----------|-------------|
| checkpointing/ | Checkpointer factory — creation, configuration, and cleanup for SQLite/PostgreSQL/Memory backends. |
| context/ | Context lifecycle management — cleanup, config, metrics, access tracking, reading, scoped offload, atomic archive storage, and restore-map sidecars. |
| events/ | Events submodule. |
| maintenance/ | Global Adaptive Maintenance Scheduling. |
| quota/ | Storage quota management and monitoring. |

## Key Dependencies

- `agent`
- `toolkits`
