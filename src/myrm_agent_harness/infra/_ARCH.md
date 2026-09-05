# infra/

## Overview
Infrastructure layer.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Infrastructure layer. | — |
| atomic_write.py | Core | Atomic file write with crash-consistency guarantee. | ✅ |
| sqlite_backup.py | Core | SQLite hot-backup manager with integrity verification, SHA-256 checksum, quarantine, and manifest tracking. | ✅ |
| sqlite_backup_models.py | Core | Data models and low-level SQLite PRAGMA utilities for sqlite_backup snapshots, verification, and restore results. | ✅ |
| sqlite_salvage.py | Core | SQLite non-destructive B-Tree page-skipping rowid salvage engine with binary search bad page isolation, orphan session stub healing, native FTS rebuild, and deferred secondary index/view replay. | ✅ |
| tls_compat.py | Core | Enterprise TLS compatibility for Python 3.13+/OpenSSL 3.x. Narrow relaxation of VERIFY_X509_STRICT for corporate TLS-inspection proxies. Provides `create_httpx_client()` factory for unified TLS-compat injection across all outbound HTTPS exits. | ✅ |

| Submodule | Description |
|-----------|-------------|
| concurrency/ | Async coordination primitives for bounded parallel work and serialized state merges. |
| delivery/ | Message delivery queue. Disk-persistent with automatic retry on failure and pending delivery recover |
| git/ | Pure-Python zero-subprocess Git metadata resolver (branch, commit, worktrees, detached HEAD) with mtime debounce. |
| incremental/ | Incremental state tracking for monitoring data changes. |
| health/ | Health checking infrastructure. Abstract interfaces for resource health checks and automatic recovery. |
| locks/ | Unified locking mechanisms for concurrent operations. |
| pubsub/ | Generic in-process pub-sub (`PubSubBus`); Server SSE / pairing / btw. Distinct from `runtime/events/` and `agent/streaming/broadcast/`. |
| security/ | Infrastructure security module. |
| tracing/ | OpenTelemetry distributed tracing. Distinct from `observability/tracing/` (stdlib log trace_id). |

## Key Dependencies

- `utils` (logger, files)
