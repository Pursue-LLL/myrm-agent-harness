# decoupled_dreaming/

## Overview
Decoupled memory consolidation, nightly dreaming engine, and serverless state synchronization subsystem. Provides direct detached memory volume I/O channels operating with zero container startup overhead, biological sleep/dreaming-inspired consolidation and decay pruning pipelines, atomic golden snapshot persistence, and lock-free cross-sandbox state synchronization broadcasting.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package facade exporting decoupled dreaming types, drive channels, consolidation pipelines, and suite facade. | — |
| dreaming_types.py | Types | Strongly typed data structures for memory drive specs, episodic interaction logs, consolidated concepts, golden snapshots, and broadcast events. | ✅ |
| direct_drive_channel.py | Core | Ultra-lightweight direct filesystem/database driver accessing persistent memory volumes without booting full code sandboxes. | ✅ |
| nightly_dreaming_pipeline.py | Core | Biological dreaming consolidation engine performing decay pruning, entity aliasing, and golden snapshot synthesis. | ✅ |
| snapshot_broadcaster.py | Core | Lock-free snapshot broadcaster notifying concurrent agent sandboxes of newly consolidated golden snapshots. | ✅ |
| decoupled_dreaming_suite.py | Facade | Unified facade suite orchestrating detached drive I/O, dreaming consolidation, atomic persistence, and cross-sandbox broadcast. | ✅ |

## Key Dependencies

- stdlib: `time`, `hashlib`, `uuid`, `json`, `pathlib`, `re`, `dataclasses`, `typing`
- Internal: `myrm_agent_harness.agent.context_management`
