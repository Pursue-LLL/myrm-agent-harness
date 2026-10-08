# [INPUT]: None
# [OUTPUT]: SchemaVersion, ShardAddress, ContentShard, ChatHeadPointer, VersionGateResult, CasSyncResult, AssembleResult
# [POS]: agent/context_management/chat_head_sync/chat_head_types.py

"""Domain contracts and types for chat head pointer and immutable shard synchronization.

[INPUT]
- None (Self-contained strongly-typed domain definitions).

[OUTPUT]
- SchemaVersion: Semantic version (major, minor) for schema compatibility checking.
- ShardAddress: Immutable content-address (sha256, byte_length) locating a shard.
- ContentShard: Immutable transcript partition containing serialized entries and sequence range.
- ChatHeadPointer: Lightweight mutable chat publication pointer swapped via CAS.
- VersionGateResult: Verdict of reader admission before fetching transcript shards.
- CasSyncResult: Outcome of CAS pointer transition indicating success, fork or conflict.
- AssembleResult: Assembled transcript outcome containing verified records and audit metrics.

[POS]
Domain contracts for chat head shard sync protocol, lineage verification, and major version gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Mapping, Sequence


@dataclass(frozen=True)
class SchemaVersion:
    """Semantic schema version tuple governing chat protocol evolution."""

    major: int
    minor: int

    def is_below(self, other: SchemaVersion) -> bool:
        """Return True if self is strictly older than other."""
        if self.major != other.major:
            return self.major < other.major
        return self.minor < other.minor

    def to_tuple(self) -> tuple[int, int]:
        """Convert version to tuple for comparisons."""
        return (self.major, self.minor)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True)
class ShardAddress:
    """Immutable content address specifying an exact transcript partition by SHA-256 and byte length."""

    sha256: str
    byte_length: int

    def to_dict(self) -> dict[str, str | int]:
        """Serialize address to standard dictionary form."""
        return {
            "sha256": self.sha256,
            "byte_length": self.byte_length,
        }


@dataclass(frozen=True)
class ContentShard:
    """Immutable chunk of chat history identified purely by its content address."""

    address: ShardAddress
    data: bytes
    record_count: int
    first_seq: int
    last_seq: int
    first_record_id: str = ""
    last_record_id: str = ""

    @classmethod
    def create(
        cls,
        data: bytes,
        record_count: int,
        first_seq: int,
        last_seq: int,
        first_record_id: str = "",
        last_record_id: str = "",
    ) -> ContentShard:
        """Factory creating content shard with calculated content address."""
        computed_sha256 = hashlib.sha256(data).hexdigest()
        address = ShardAddress(sha256=computed_sha256, byte_length=len(data))
        return cls(
            address=address,
            data=data,
            record_count=record_count,
            first_seq=first_seq,
            last_seq=last_seq,
            first_record_id=first_record_id,
            last_record_id=last_record_id,
        )


@dataclass(frozen=True)
class ChatHeadPointer:
    """Small mutable publication pointer swapped via CAS representing the published chat state."""

    chat_id: str
    schema_version: SchemaVersion
    min_reader_version: SchemaVersion | None
    parent_head_sha256: str | None
    head_sha256: str
    shard_addresses: Sequence[ShardAddress]
    metadata: Mapping[str, str] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_canonical_dict(self) -> dict[str, str | int | list[dict[str, str | int]] | dict[str, str] | None]:
        """Produce canonical representation for content hash computation."""
        return {
            "chat_id": self.chat_id,
            "schema_version": f"{self.schema_version.major}.{self.schema_version.minor}",
            "min_reader_version": (
                f"{self.min_reader_version.major}.{self.min_reader_version.minor}"
                if self.min_reader_version is not None
                else None
            ),
            "parent_head_sha256": self.parent_head_sha256,
            "shard_addresses": [addr.to_dict() for addr in self.shard_addresses],
            "metadata": dict(sorted(self.metadata.items())),
        }


@dataclass(frozen=True)
class VersionGateResult:
    """Verdict of reader admission checking before part fetching."""

    ok: bool
    reason: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class CasSyncResult:
    """Outcome of CAS pointer update operation."""

    ok: bool
    new_head_sha256: str | None = None
    current_head_sha256: str | None = None
    fork_detected: bool = False
    error_message: str | None = None
    new_shards_uploaded: int = 0


@dataclass(frozen=True)
class AssembleResult:
    """Result of assembling whole transcript from head and immutable shards."""

    ok: bool
    chat_id: str
    assembled_records: Sequence[bytes] = field(default_factory=list)
    total_bytes: int = 0
    shards_loaded: int = 0
    error_message: str | None = None
    gate_reason: str | None = None
