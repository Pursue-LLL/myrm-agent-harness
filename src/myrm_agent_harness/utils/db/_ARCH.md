# db/

## Overview
Database utilities: SQLite migration management plus the unified SQLite hardening
factory (durability / privacy / crash-recovery for every store in the framework).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Database utilities for SQLite migration management. | — |
| fts5.py | Core | FTS5 Utilities | ✅ |
| migration_engine.py | Core | Zero-ops stateful SQLite migration engine. Provides version tracking, precise timing, | ✅ |
| sqlite/ | Subpackage | Unified SQLite hardening factory: `SQLiteProfile` presets, sync/async connection hardening with an EIO-safe WAL fallback, and file-level integrity/crash-recovery primitives. See [`sqlite/_ARCH.md`](sqlite/_ARCH.md). | ✅ |
