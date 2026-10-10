# Snapshot Lag Aware Memory Freshness and Disk Verification Contract Suite Architecture

## Overview
The Snapshot Lag Aware Memory Freshness Suite solves the cognitive divergence where LLM agents update facts on disk during a multi-turn conversation, but continue contradicting themselves because the System Context holds the stale memory snapshot loaded at session start. By stamping memory snapshots with unique digests, flagging dirty states upon memory writes, injecting direct-disk read hints, and rendering intra-session delta patch blocks at the tail of prompts, the system eliminates contradiction without invalidating prompt KV cache prefixes.

## Components

| File | Type | Description |
|---|---|---|
| `models.py` | Data Models | Domain models including `MemorySnapshotDigest`, `SessionWriteDelta`, `SnapshotFreshnessState`, `DirectDiskReadHint`, and `DeltaPatchBlock`. |
| `freshness_tracker.py` | Core Tracker | In-memory session tracker maintaining snapshot generation digests, tracking ongoing write deltas, generating contract hints, and rendering delta patches. |
| `__init__.py` | Facade | Public package API exports. |

## Data Flow
```
[Session Start: Injected Memory]
              │
              ▼
   SnapshotFreshnessTracker
   (Hash Digest stamped: v1)
              │
   (During session: memory_store)
              │
              ▼
    [record_write(key, content)]
              │
              ├─────────────────────────────────────────┐
              ▼                                         ▼
   is_dirty = True & v2                      DirectDiskReadHint
              │                              (Direct disk read prompt)
              ▼
    [render_delta_patch]
    (Tail Markdown block: v2 updates override v1 snapshot)
```
