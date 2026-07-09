# runtime/

## Overview

Single Agent **instance** survival layer — checkpoint, context lifecycle, quota, doctor, memory
pressure. **Not** the Agent reasoning loop (`agent/`) and **not** generic job queues (`toolkits/tasks/`).

Layer cheatsheet: [ARCHITECTURE.md](../../../ARCHITECTURE.md) §Harness 五层落点.

Detailed design: [CONVERSATION_FORK_SYSTEM.md](CONVERSATION_FORK_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent runtime infrastructure for single-instance execution. | — |
| artifact_judge.py | Core | Artifact identification system. | ✅ |
| checkpoint_protocol.py | Core | CheckpointerProtocol for type-safe checkpointer thread store access. | ✅ |
| compression.py | Core | Generic file compression utilities for storage optimization. | ✅ |
| doctor.py | Core | Concurrent diagnostic engine. Async-parallel model with lightweight HTTP probe, deploy mode awareness, and structured diagnostics. | ✅ |
| doctor_cli.py | Core | CLI Formatter for Myrm Doctor. | ✅ |
| execution_paths.py | Core | Unified execution path constants and utilities, including content-addressed context archive metadata, restore-map sidecar paths, and archive sidecar path candidate normalization. | ✅ |
| fork_types.py | Config | Defines data structures for conversation forking feature. Used by business layer | ✅ |
| memory_pressure.py | Core | Global memory pressure coordination. Framework provides the monitor and hooks; | ✅ |
| resource_monitor.py | Core | High-fidelity resource monitor with history sampling, adaptive heap profiling, and production-visible [MEMORY] INFO logging. | ✅ |
| startup.py | Core | Optional toolkit for monitoring application startup performance. | ✅ |
| lazy_deps.py | Core | Allowlisted venv-scoped lazy install for optional platform extras (Matrix, Discord, Feishu, WeChat SILK). | ✅ |

| Submodule | Description |
|-----------|-------------|
| checkpointing/ | Checkpointer factory — creation, configuration, and cleanup for SQLite/Memory backends. |
| context/ | Context lifecycle management — cleanup, config, metrics, access tracking, reading, scoped offload, atomic archive storage, and restore-map sidecars. |
| events/ | Events submodule. |
| maintenance/ | Global Adaptive Maintenance Scheduling. |
| quota/ | Storage quota management and monitoring. |

## Key Dependencies

- `agent`
- `toolkits`
