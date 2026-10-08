"""Comprehensive facade suite for chat head pointer and immutable shard synchronization.

[INPUT]
- AssembleResult, CasSyncResult, ChatHeadPointer, ContentShard, SchemaVersion, ShardAddress, VersionGateResult:
  Domain types from chat_head_types.

[OUTPUT]
- ChatHeadShardSyncSuite: Orchestration facade providing atomic CAS publication,
  hash-diff partition management, lineage-based fork detection, and version gating.

[POS]
Top-level entrypoint for chat head shard sync protocol in agent context management.
"""

from __future__ import annotations

import json
import time
from typing import Mapping, Sequence

from .chat_head_lineage_resolver import (
    compute_head_sha256,
    detect_head_fork,
    verify_lineage_cas,
)
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


class ChatHeadShardSyncSuite:
    """Orchestration facade coordinating chat head pointers and immutable content shards.

    Core Guarantees:
    1. Small mutable head pointer swapped via CAS: Head record stays lightweight (KB scale).
    2. Shard immutability & content-addressing: (sha256, byteLength) identifies parts.
    3. Cryptographic Lineage & Fork Detection: parentHeadSha256 chains publications;
       never relies on turn sequence numbers which permit dangerous overwrites.
    4. Major-only version gate with minReader safety floor: same-major passthrough admits
       newer minors; minReaderVersion protects breaking behavioral changes.
    """

    def __init__(self, storage_engine: ChatShardStorageEngine | None = None) -> None:
        self._storage = storage_engine or ChatShardStorageEngine()
        self._heads: dict[str, ChatHeadPointer] = {}
        self._lineage_graph: dict[str, str | None] = {}

    @property
    def storage(self) -> ChatShardStorageEngine:
        """Return the underlying content shard storage engine."""
        return self._storage

    def get_head(self, chat_id: str) -> ChatHeadPointer | None:
        """Fetch current head pointer for a chat."""
        return self._heads.get(chat_id)

    def publish_with_cas(
        self,
        chat_id: str,
        shards: Sequence[ContentShard],
        expected_parent_head_sha256: str | None,
        schema_version: SchemaVersion,
        min_reader_version: SchemaVersion | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> CasSyncResult:
        """Publish a chat update using Compare-And-Swap on the head pointer.

        Args:
            chat_id: Unique chat identifier.
            shards: Complete ordered list of content shards forming the transcript.
            expected_parent_head_sha256: The head SHA-256 the publisher believes it is updating.
            schema_version: Publication schema version.
            min_reader_version: Optional reader version floor required for safe interpretation.
            metadata: Custom chat metadata.

        Returns:
            CasSyncResult: Details of whether CAS succeeded, or fork/collision was detected.
        """
        current_head = self._heads.get(chat_id)
        current_sha256 = current_head.head_sha256 if current_head is not None else None

        valid, reason = verify_lineage_cas(current_head, expected_parent_head_sha256)
        if not valid:
            return CasSyncResult(
                ok=False,
                current_head_sha256=current_sha256,
                fork_detected=True,
                error_message=reason or "CAS collision detected",
                new_shards_uploaded=0,
            )

        # Persist shards and track newly uploaded partitions
        newly_uploaded = 0
        addresses: list[ShardAddress] = []
        for shard in shards:
            if not self._storage.has_shard(shard.address.sha256):
                self._storage.put_shard(
                    data=shard.data,
                    record_count=shard.record_count,
                    first_seq=shard.first_seq,
                    last_seq=shard.last_seq,
                    first_record_id=shard.first_record_id,
                    last_record_id=shard.last_record_id,
                )
                newly_uploaded += 1
            addresses.append(shard.address)

        # Compute new deterministic head SHA-256
        meta = dict(metadata or {})
        new_head_sha256 = compute_head_sha256(
            chat_id=chat_id,
            schema_version=schema_version,
            min_reader_version=min_reader_version,
            parent_head_sha256=expected_parent_head_sha256,
            shard_addresses=addresses,
            metadata=meta,
        )

        new_head = ChatHeadPointer(
            chat_id=chat_id,
            schema_version=schema_version,
            min_reader_version=min_reader_version,
            parent_head_sha256=expected_parent_head_sha256,
            head_sha256=new_head_sha256,
            shard_addresses=addresses,
            metadata=meta,
            updated_at=time.time(),
        )

        # Advance pointer
        self._heads[chat_id] = new_head
        self._lineage_graph[new_head_sha256] = expected_parent_head_sha256

        return CasSyncResult(
            ok=True,
            new_head_sha256=new_head_sha256,
            current_head_sha256=new_head_sha256,
            fork_detected=False,
            error_message=None,
            new_shards_uploaded=newly_uploaded,
        )

    def fetch_and_assemble(
        self,
        chat_id: str,
        reader_supports: SchemaVersion,
    ) -> AssembleResult:
        """Check version gate on head and assemble transcript from immutable shards.

        Crucial optimization: Version gate evaluates on the lightweight head row.
        If rejected, zero shards are loaded, incurring 0 egress and 0 memory allocation.
        """
        head = self._heads.get(chat_id)
        if head is None:
            return AssembleResult(
                ok=False,
                chat_id=chat_id,
                error_message=f"Chat head for '{chat_id}' not found",
            )

        gate_verdict: VersionGateResult = gate_chat_head_version(head, reader_supports)
        if not gate_verdict.ok:
            return AssembleResult(
                ok=False,
                chat_id=chat_id,
                gate_reason=gate_verdict.reason,
                error_message=gate_verdict.message,
                shards_loaded=0,
                total_bytes=0,
            )

        # Version gate admitted reader; proceed to assemble immutable shards
        assembled_data: list[bytes] = []
        total_bytes = 0
        shards_loaded = 0

        for addr in head.shard_addresses:
            shard = self._storage.get_shard(addr)
            if shard is None:
                return AssembleResult(
                    ok=False,
                    chat_id=chat_id,
                    error_message=f"Missing immutable shard '{addr.sha256}' during assembly",
                    shards_loaded=shards_loaded,
                    total_bytes=total_bytes,
                )
            assembled_data.append(shard.data)
            total_bytes += len(shard.data)
            shards_loaded += 1

        return AssembleResult(
            ok=True,
            chat_id=chat_id,
            assembled_records=assembled_data,
            total_bytes=total_bytes,
            shards_loaded=shards_loaded,
        )

    def is_forked(self, head_a: ChatHeadPointer, head_b: ChatHeadPointer) -> bool:
        """Determine if two heads represent an unreconciled fork."""
        return detect_head_fork(head_a, head_b, self._lineage_graph)

    @classmethod
    def create(cls) -> ChatHeadShardSyncSuite:
        """Create a default ChatHeadShardSyncSuite instance."""
        return cls()
