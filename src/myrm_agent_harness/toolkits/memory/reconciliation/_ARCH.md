# Disk Memory FTS Reconciliation Loop & Explicit Write Gate Suite Architecture

## 1. Positioning & Overview
The `reconciliation` package implements bi-directional synchronization between physical disk markdown memory files and SQLite FTS5 search indexes, alongside explicit typed write gates for `myrm-agent-harness`.
Inspired by Xiaomi MiMo Code (`reconcile.ts` & `write-gate.ts`), it eliminates ghost search results from deleted files and prevents background blind-write pollution during read-only or inspection sessions.

## 2. Key Components
1. **`models.py`**:
   - `DiskMemoryFileMeta`: Content SHA-256 fingerprint, mtime, title, and file path.
   - `ReconciliationReport`: Complete metrics covering scanned, indexed, and pruned counts.
   - `WriteGatePolicy`: Typed policies (`ENABLED`, `READ_ONLY_SESSION`, `DISABLED_TEMPORARY`, `DISABLED_CONFIG_FAULT`).
   - `WriteGateCheckResult` & `FtsReconciledHit`.
2. **`write_gate.py` (`MemoryWriteGate`)**:
   - Strictly decouples reads from writes: reads are always open and unaffected.
   - Manages global and session-specific overrides; raises `MemoryWriteBlockedError` on forbidden write attempts.
3. **`disk_reconciler.py` (`DiskMemoryFtsReconciler`)**:
   - **Direction A (Index Disk Files)**: Discovers new and modified `.md` files via SHA-256 hash comparison and synchronizes them into SQLite FTS5.
   - **Direction B (Prune Dead Rows)**: Computes the difference between indexed DB records and active disk paths (`indexed - disk`), physically pruning deleted files from both relational and FTS virtual tables.

## 3. Boundary & Non-Goals
- Single-machine, local-first SQLite WAL storage.
- Zero `Any` types across all interfaces.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for reconciliation. | ✅ |
| `disk_reconciler.py` | Core | Bi-directional reconciliation engine synchronizing disk Markdown files with SQLite FTS5. | ✅ |
| `models.py` | Types | Types and models for reconciliation. | ✅ |
| `write_gate.py` | Core | Explicit gate decoupler enforcing read-always-open vs write-permission-checked policies. | ✅ |
