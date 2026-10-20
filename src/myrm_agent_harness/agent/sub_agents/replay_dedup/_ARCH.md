# replay_dedup/

## Overview
Package initialization for Multi-Agent Tool Replay History Deduplication & Harmonization (Item 57).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package initialization for Multi-Agent Tool Replay History Deduplication & Harmonization (Item 57). — High-level exports for ToolReplayHistoryMerger and SubagentStatusHarmonizer. | — |
| `harmonizer.py` | Core | Subagent Tool Status Harmonizer & Anti-Deadlock Machine (Item 57). — Monotonically progressive status state machine transitions and audit events | ✅ |
| `merger.py` | Core | Tool Replay History Deduplication & Consecutive Read-Only Call Merger (Item 57). — ReplayDeduplicationResult containing aggregated MergedReplayBatch instances | ✅ |
| `types.py` | Types | Core types for Multi-Agent Tool Replay History Deduplication & Subagent Status Harmonization (Item 57). — Strongly-typed models for consecutive tool call batching, token compact metrics, | ✅ |
