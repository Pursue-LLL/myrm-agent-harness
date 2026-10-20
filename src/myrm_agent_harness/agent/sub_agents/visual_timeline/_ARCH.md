# visual_timeline/

## Overview
Multi-Agent Visual Timeline & Cherry-Pick Rollback Package (Item 61).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Multi-Agent Visual Timeline & Cherry-Pick Rollback Package (Item 61). — Public module exports for collaborative visual timeline and single-agent surgical undo. | — |
| `cherry_pick_engine.py` | Core | Surgical Cherry-Pick Rollback Engine for individual agent actions (Item 61). — RollbackResult indicating SUCCESS, CONFLICT_DETECTED, or ALREADY_ROLLED_BACK.; Precise reverse-patched content without affecting other collaborators' work. | ✅ |
| `timeline_journal.py` | Core | Activity timeline journal and multi-dimensional query store (Item 61). — Chronologically indexed timeline event logs per session.; Filtered timeline slices by actor, role, file path, operation, and timestamp. | ✅ |
| `types.py` | Types | Core types and data contracts for Multi-Agent Visual Timeline & Cherry-Pick Rollback (Item 61). — ActorType, OperationType, RollbackStatus, | ✅ |
