# [INPUT]: durable_storage_types, durable_storage_protocol, memory_durable_storage, jsonl_durable_storage, sqlite_durable_storage, durable_storage_suite
# [OUTPUT]: BenchmarkMetrics, CommitMarker, CommitWrite, ConversationRecord, DocumentRecord, DurableStorageProtocol, EntryRecord, JsonlDurableStorage, MemoryDurableStorage, PortableDurableStorageSuite, SqliteDurableStorage, StorageBackendKind, StorageWriteKind, TaskRecord
# [POS]: agent/context_management/durable_storage/__init__.py

"""Portable durable storage runtime package supporting Memory, JSONL, and SQLite backends.

[INPUT]
- durable_storage_types: Domain contracts, records, and markers.
- durable_storage_protocol: Common storage interface protocol.
- memory_durable_storage: Zero-IO in-memory backend.
- jsonl_durable_storage: Append-only JSONL stream backend with commit markers.
- sqlite_durable_storage: Relational ACID SQLite backend with WAL mode.
- durable_storage_suite: Unified orchestration facade and benchmark runner.

[OUTPUT]
- Canonical exports for durable storage subsystem.

[POS]
Modular implementation of portable durable storage runtime across sandbox, desktop, and local environments.
"""

from __future__ import annotations

from .durable_storage_protocol import DurableStorageProtocol
from .durable_storage_suite import PortableDurableStorageSuite
from .durable_storage_types import (
    BenchmarkMetrics,
    CommitMarker,
    CommitWrite,
    ConversationRecord,
    DocumentRecord,
    EntryRecord,
    StorageBackendKind,
    StorageWriteKind,
    TaskRecord,
)
from .jsonl_durable_storage import JsonlDurableStorage
from .memory_durable_storage import MemoryDurableStorage
from .sqlite_durable_storage import SqliteDurableStorage

__all__ = [
    "BenchmarkMetrics",
    "CommitMarker",
    "CommitWrite",
    "ConversationRecord",
    "DocumentRecord",
    "DurableStorageProtocol",
    "EntryRecord",
    "JsonlDurableStorage",
    "MemoryDurableStorage",
    "PortableDurableStorageSuite",
    "SqliteDurableStorage",
    "StorageBackendKind",
    "StorageWriteKind",
    "TaskRecord",
]
