# governance/

## Overview

Unified four-dimensional memory governance engine for AI agents.
Integrates Profile Slots (deterministic sorted prefix for Prompt Cache), Event Timelines, Dynamic Facts with TTL and four-state reconciliation, and bounded 2-hop Entity Graph traversal.

Detailed design: [MEMORY_SYSTEM.md](../MEMORY_SYSTEM.md)

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Aggregated export for the memory governance package. | ✅ |
| `models.py` | Core | ProfileSlots, DynamicFactItem, EventTimelineItem, ReconciliationDecision, AssembledMemoryContext. | ✅ |
| `reconciler.py` | Core | FactReconciliationEngine (ADD/UPDATE/DELETE/NOOP four-state reconciliation and TTL pruning). | ✅ |
| `graph_bridge.py` | Core | EntityGraphBridge for bounded 2-hop relation traversal backed by SQLiteGraphStore. | ✅ |
| `assembler.py` | Core | DynamicContextAssembler enforcing token budgets and deterministic cache-friendly prefix serialization. | ✅ |

## Key Dependencies

- `myrm_agent_harness.toolkits.memory.graph`
