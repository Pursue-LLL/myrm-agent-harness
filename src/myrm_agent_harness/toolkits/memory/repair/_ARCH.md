# Memory Integrity Repair & Stale Pruning Architecture

## Overview
This toolkit provides automated physical integrity diagnostics, self-healing database restoration, adaptive utility decay pruning, and prompt cache preservation barriers for the Myrm agent memory substrate (Item 73).

## Core Modules
- `models.py`: Strongly typed primitives (`IntegrityCheckReport`, `RepairReport`, `StalePrunePolicy`, `PruneSummary`, `HealthMetric`).
- `detector.py`: `DatabaseIntegrityDetector` executing non-destructive `PRAGMA integrity_check`, `quick_check`, and FTS consistency probes.
- `healer.py`: `DatabaseAutoHealer` restoring indexes via `REINDEX`, FTS table rebuild, and WAL checkpoint flush.
- `pruner.py`: `StaleEntryPruner` implementing exponential utility decay: $U = (1 + \ln(1 + \text{recall\_count})) \cdot \exp(-\lambda \Delta t)$.
- `barrier.py`: `CachePreservingCompactionBarrier` guarding active session snapshot prefixes from prompt cache invalidation.
- `service.py`: `MemoryRepairService` unified facade integrating detector, healer, pruner, and barrier.
- `__init__.py`: Public package exports conforming to harness conventions.
