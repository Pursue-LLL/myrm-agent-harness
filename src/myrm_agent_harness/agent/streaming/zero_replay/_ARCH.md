# streaming/zero_replay/

## Overview
Zero-Replay reconnect protocol engine and atomic state snapshot models (inspired by earendil-works/pi harness-v2 UI model).
Eliminates client-side UI flickering, duplicate re-renders, and event disorder upon network reconnects by separating atomic state snapshots from pure live-stream delta events.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | Re-exports core zero-replay models and protocol engine. | — |
| `snapshot_models.py` | Models | Data contracts for SessionAtomicSnapshot, LiveStreamFilterConfig, and lifecycle statuses. | ✅ |
| `zero_replay_engine.py` | Core | Protocol engine managing monotonic state versions, epochs, and live-event gating filters. | ✅ |
| `_ARCH.md` | Architecture | Architectural documentation and component taxonomy. | — |

## Key Principles
1. **Atomic Snapshot Baseline**: Client fetches one atomic snapshot representing the latest coherent state tree.
2. **Zero Historical Replay**: Live event stream only forwards events emitted AFTER the snapshot timestamp with strictly incremented state versions.
3. **Epoch Fencing**: Stale client epochs or negative version drift trigger full atomic reload instead of error-prone delta replaying.
