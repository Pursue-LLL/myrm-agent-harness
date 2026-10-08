"""Domain contracts and models for portable durable storage runtimes.

[INPUT]
- None (Self-contained strongly-typed contracts).

[OUTPUT]
- StorageWriteKind: Enumeration of atomic storage write operations.
- StorageBackendKind: Classification of storage engines (memory, jsonl, sqlite).
- ConversationRecord: Root/branch conversation descriptor.
- EntryRecord: Ordered immutable transcript or message entry.
- TaskRecord: Live or terminal agent task execution record.
- DocumentRecord: Strongly typed state document with versions.
- CommitWrite: Atomic write directive passed into storage transaction.
- CommitMarker: Integrity seal verifying completed commit block in stream logs.
- BenchmarkMetrics: Deterministic profiling metrics for storage conformance.

[POS]
Domain models for uniform durable storage runtime across memory, JSONL, and SQLite backends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Mapping, Sequence


class StorageWriteKind(str, Enum):
    """Types of durable atomic writes supported by the storage engine."""

    CONVERSATION = "conversation"
    ENTRY = "entry"
    TASK = "task"
    DOCUMENT = "document"


class StorageBackendKind(str, Enum):
    """Storage backend implementations adhering to the common storage contract."""

    MEMORY = "memory"
    JSONL = "jsonl"
    SQLITE = "sqlite"


@dataclass(frozen=True)
class ConversationRecord:
    """Canonical durable conversation descriptor."""

    id: str
    owner_task_id: str | None = None
    title: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class EntryRecord:
    """Ordered transcript entry identified by monotonic sequence number."""

    id: str
    conversation_id: str
    seq: int
    kind: str
    payload: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TaskRecord:
    """Execution state and checkpoint for background or foreground tasks."""

    id: str
    conversation_id: str
    kind: str
    status: str
    checkpoint: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)
    abort_requested: bool = False
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class DocumentRecord:
    """Versioned structured document state committed alongside session entries."""

    id: str
    version: int
    content: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CommitWrite:
    """Individual atomic write operation bundled in a commit transaction."""

    kind: StorageWriteKind
    id: str
    payload: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(frozen=True)
class CommitMarker:
    """Integrity marker concluding an atomic commit block in stream backends."""

    format_version: int
    seq: int
    writes_count: int
    checksum: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float]:
        """Convert marker to serializable dictionary."""
        return {
            "format_version": self.format_version,
            "seq": self.seq,
            "writes_count": self.writes_count,
            "checksum": self.checksum,
            "timestamp": self.timestamp,
        }

    @classmethod
    def compute_checksum(cls, seq: int, writes: Sequence[CommitWrite]) -> str:
        """Compute cryptographic checksum sealing the commit batch."""
        canonical_raw = f"{seq}:" + ";".join(
            f"{w.kind.value}:{w.id}:{json.dumps(dict(sorted(w.payload.items())), sort_keys=True)}"
            for w in writes
        )
        return hashlib.sha256(canonical_raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Metrics produced by deterministic storage benchmark suite."""

    backend: StorageBackendKind
    commit_latency_ms: float
    point_read_latency_ms: float
    range_scan_latency_ms: float
    reopen_latency_ms: float
    records_count: int
    memory_footprint_kb: float
