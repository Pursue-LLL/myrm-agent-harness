# agent/durable/

## Overview

Durable stateful agent runtime, Intent-First ledger, and crash recovery replay engine.

Enables mathematical determinism and side-effect safety across process termination, system sleep, OOM, and crashes.

---

## Architecture Principles

1. **Intent-First Durability Rule**: Prior to executing any external side-effect (model inference, tool mutation, context compact), an `IntentRecord` with a pre-provisioned `resultEntryId` is persisted to SQLite WAL. Upon completion, the result is appended using the exact same ID.
2. **Four-Tier Decoupled State Model**:
   - `Tree`: Append-only, immutable dialogue history protecting Prompt Cache $\ge 95\%$.
   - `Lanes`: Parallel swimlanes with independent leaf pointers.
   - `Operation Logs`: Transient scheduler and intent events decoupled from LLM context.
   - `Global Facts`: Session-level configurations and facts.
3. **Dual Replay Safety Verification & Synthetic Interrupted Fallback**: Tools with external mutations are intercepted upon recovery; a structured `ToolExecutionInterruptedError` is synthesized to guide the LLM to inspect environment state before retrying.
4. **Single-Writer FIFO Mutation Line**: `LaneMutationLine` serializes steer, follow-up, finish, and abort decisions, eliminating Check-Then-Act concurrency races.

---

## File & Submodule Index

| File | Role | Description |
|---|---|---|
| `types.py` | Data Contracts | `IntentRecord`, `TreeEntry`, `LaneState`, `OperationLogEntry`, `UsageRecord`, `ReplayDecision` (all dataclasses with `slots=True`). |
| `protocols.py` | Interfaces | `DurableStorageProtocol`, `EffectsBoundaryProtocol`, `ToolSafetyClassifierProtocol`. |
| `storage.py` | Storage Engine | Production SQLite WAL 5-table backend + ultra-fast `InMemoryDurableStorage`. |
| `mutation_line.py` | Concurrency | `LaneMutationLine` FIFO single-writer queue eliminating check-then-act races. |
| `intent_engine.py` | Core Protocol | `IntentExecutionEngine` coordinating pre-allocation and post-append. |
| `replay_auditor.py` | Replay Safety | `ReplaySafetyAuditor` and `DefaultToolSafetyClassifier` determining re-run vs synthetic fallback. |
| `effects_gate.py` | Effects Boundary | `ManualDriveEffectsGate` enabling mechanical crash injection in tests. |
| `runtime.py` | Orchestrator | `DurableAgentRuntime` and `RecoverySummary` unified lifecycle manager. |
| `__init__.py` | Facade | Public package exports. |
