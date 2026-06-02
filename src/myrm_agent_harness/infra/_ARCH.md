# infra/

## Overview
Infrastructure layer.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Infrastructure layer. | — |
| atomic_write.py | Core | Atomic file write with crash-consistency guarantee. | ✅ |
| sqlite_backup.py | Core | SQLite hot-backup manager with integrity verification, SHA-256 checksum, quarantine, and manifest tracking. | ✅ |

| Submodule | Description |
|-----------|-------------|
| cache/ | Framework infrastructure layer. Used by config caching, storage caching, etc. |
| concurrency/ | Async coordination primitives for bounded parallel work and serialized state merges. |
| delivery/ | Message delivery queue. Disk-persistent with automatic retry on failure and pending delivery recover |
| incremental/ | Incremental state tracking for monitoring data changes. |
| health/ | Health checking infrastructure. Abstract interfaces for resource health checks and automatic recovery. |
| locks/ | Unified locking mechanisms for concurrent operations. |
| security/ | Infrastructure security module. |
| tracing/ | Distributed tracing and metrics collection. Integrates OpenTelemetry for call chain tracing, perform |

## Key Dependencies

- `utils` (logger, files)
