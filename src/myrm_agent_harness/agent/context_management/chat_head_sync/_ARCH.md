# chat_head_sync/

## Overview

Chat head pointer and immutable shard synchronization protocol subsystem. Enforces lightweight mutable head pointer CAS transitions, immutable content-addressed shard storage, lineage verification via parentHeadSha256 (preventing sequence-number-based fork overwrites), and reader version gating that admits same-major schema evolution while enforcing minReaderVersion safety floors.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Chat head and immutable shard synchronization protocol package entry point. | ✅ |
| `chat_head_lineage_resolver.py` | Core | Cryptographic head SHA-256 computation, CAS lineage validation, and fork detection. | ✅ |
| `chat_head_shard_sync_suite.py` | Facade | Unified orchestration suite coordinating CAS head updates, shard storage, and gated assembly. | ✅ |
| `chat_head_types.py` | Types | Domain contracts, schema versions, shard addresses, and synchronization receipts. | ✅ |
| `chat_head_version_gate.py` | Core | Reader admission gate enforcing major-only rejection and minReaderVersion safety floors. | ✅ |
| `chat_shard_storage_engine.py` | Storage | Content-addressed immutable shard storage engine with hash-diff differential sync. | ✅ |
