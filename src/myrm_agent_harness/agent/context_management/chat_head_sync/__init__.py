# [INPUT]: chat_head_types, chat_head_lineage_resolver, chat_shard_storage_engine, chat_head_version_gate, chat_head_shard_sync_suite
# [OUTPUT]: ChatHeadShardSyncSuite, ChatShardStorageEngine, ChatHeadPointer, ContentShard, SchemaVersion, ShardAddress, VersionGateResult, CasSyncResult, AssembleResult, gate_chat_head_version, compute_head_sha256, verify_lineage_cas, detect_head_fork
# [POS]: agent/context_management/chat_head_sync/__init__.py

"""Chat head pointer and immutable shard synchronization protocol package.

[INPUT]
- chat_head_types: Core domain data structures.
- chat_head_lineage_resolver: CAS parent hash verification and lineage resolution.
- chat_shard_storage_engine: Immutable content-addressed partition store.
- chat_head_version_gate: Version admission gate with major rejection and minReader floors.
- chat_head_shard_sync_suite: Orchestration facade for atomic publication and assembly.

[OUTPUT]
- Canonical exports for chat head sync protocol.

[POS]
Modular implementation of lightweight chat head CAS pointers and immutable content-addressed shards.
"""

from __future__ import annotations

from .chat_head_lineage_resolver import (
    compute_head_sha256,
    detect_head_fork,
    verify_lineage_cas,
)
from .chat_head_shard_sync_suite import ChatHeadShardSyncSuite
from .chat_head_types import (
    AssembleResult,
    CasSyncResult,
    ChatHeadPointer,
    ContentShard,
    SchemaVersion,
    ShardAddress,
    VersionGateResult,
)
from .chat_head_version_gate import gate_chat_head_version
from .chat_shard_storage_engine import ChatShardStorageEngine

__all__ = [
    "AssembleResult",
    "CasSyncResult",
    "ChatHeadPointer",
    "ChatHeadShardSyncSuite",
    "ChatShardStorageEngine",
    "ContentShard",
    "SchemaVersion",
    "ShardAddress",
    "VersionGateResult",
    "compute_head_sha256",
    "detect_head_fork",
    "gate_chat_head_version",
    "verify_lineage_cas",
]
