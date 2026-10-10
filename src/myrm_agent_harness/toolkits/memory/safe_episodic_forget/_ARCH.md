# safe_episodic_forget/

## Overview

Safe episodic memory forget suite ensuring authorization predicates, cross-tier shared child retention, immediate write lock probe/cascades in a single transaction, and after-commit invalidation event emission.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Facade export for safe episodic forget components and models. | ✅ |
| `models.py` | Types | Domain models for forget requests, probe results, and events. | ✅ |
| `transaction_hooks.py` | Core | Transaction lifecycle and after-commit hook manager with savepoint isolation. | ✅ |
| `sqlite_adapter.py` | Storage | SQLite schema management, multi-tier tables, and immediate write lock context. | ✅ |
| `engine.py` | Core | Safe episodic forget engine implementing authorization and retention guards. | ✅ |
