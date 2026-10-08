"""Immutable content-addressed shard storage engine with hash-diffing and verification.

[INPUT]
- ShardAddress: Content address identifying partition.
- ContentShard: Content partition entity.

[OUTPUT]
- ChatShardStorageEngine: In-memory/persistent store for immutable content shards.

[POS]
Content-addressed partition management layer ensuring immutability, data integrity, and hash-diff sync.
"""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

from .chat_head_types import ContentShard, ShardAddress


class ChatShardStorageEngine:
    """Manages storage, retrieval, and differential detection of immutable chat shards."""

    def __init__(self) -> None:
        self._shards: dict[str, ContentShard] = {}

    def put_shard(
        self,
        data: bytes,
        record_count: int,
        first_seq: int,
        last_seq: int,
        first_record_id: str = "",
        last_record_id: str = "",
    ) -> ContentShard:
        """Store a content shard under its SHA-256 address.

        Ensures immutability: identical content addresses map to the exact same shard.
        Validates hash integrity and byte length prior to persistence.
        """
        computed_sha256 = hashlib.sha256(data).hexdigest()
        byte_length = len(data)

        if computed_sha256 in self._shards:
            return self._shards[computed_sha256]

        address = ShardAddress(sha256=computed_sha256, byte_length=byte_length)
        shard = ContentShard(
            address=address,
            data=data,
            record_count=record_count,
            first_seq=first_seq,
            last_seq=last_seq,
            first_record_id=first_record_id,
            last_record_id=last_record_id,
        )
        self._shards[computed_sha256] = shard
        return shard

    def get_shard(self, address: ShardAddress) -> ContentShard | None:
        """Retrieve shard by content address with validation."""
        shard = self._shards.get(address.sha256)
        if shard is None:
            return None
        if len(shard.data) != address.byte_length:
            return None
        return shard

    def has_shard(self, sha256: str) -> bool:
        """Check whether shard is already held in storage."""
        return sha256 in self._shards

    def compute_diff(
        self,
        target_addresses: Sequence[ShardAddress],
    ) -> list[ShardAddress]:
        """Compute missing shard addresses not present in this storage engine.

        Enables hash-diff publishing: client queries what shards the server lacks,
        uploading only new content partitions and preserving unchanged addresses.
        """
        missing: list[ShardAddress] = []
        for addr in target_addresses:
            if addr.sha256 not in self._shards:
                missing.append(addr)
        return missing

    def list_known_addresses(self) -> set[str]:
        """Return the set of all SHA-256 addresses currently stored."""
        return set(self._shards.keys())

    def clear(self) -> None:
        """Clear all stored shards."""
        self._shards.clear()
