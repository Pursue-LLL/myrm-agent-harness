"""In-memory durable storage backend implementation adhering to uniform contract.

[INPUT]
- CommitWrite, ConversationRecord, DocumentRecord, EntryRecord, StorageBackendKind, StorageWriteKind, TaskRecord:
  Domain types from durable_storage_types.
- DurableStorageProtocol: Base storage contract.

[OUTPUT]
- MemoryDurableStorage: Zero-I/O in-memory storage engine for fast unit tests and ephemeral runs.

[POS]
In-memory persistence implementation providing baseline semantics and reference behavior.
"""

from __future__ import annotations

import copy
import time
from typing import Sequence

from .durable_storage_protocol import DurableStorageProtocol
from .durable_storage_types import (
    CommitWrite,
    ConversationRecord,
    DocumentRecord,
    EntryRecord,
    StorageBackendKind,
    StorageWriteKind,
    TaskRecord,
)


class MemoryDurableStorage(DurableStorageProtocol):
    """In-memory reference implementation of the durable storage contract."""

    def __init__(self) -> None:
        self._current_seq: int = 0
        self._conversations: dict[str, ConversationRecord] = {}
        self._entries: dict[str, EntryRecord] = {}
        self._conversation_entries: dict[str, list[str]] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._documents: dict[str, DocumentRecord] = {}
        self._snapshot_state: dict[str, dict[str, ConversationRecord | EntryRecord | TaskRecord | DocumentRecord]] = {}

    @property
    def backend_kind(self) -> StorageBackendKind:
        return StorageBackendKind.MEMORY

    def commit(self, writes: Sequence[CommitWrite]) -> int:
        """Atomically apply a sequence of writes in memory."""
        self._current_seq += 1
        seq = self._current_seq

        for write in writes:
            if write.kind == StorageWriteKind.CONVERSATION:
                owner_id = str(write.payload.get("owner_task_id", "")) or None
                title = str(write.payload.get("title", ""))
                metadata = {
                    str(k): str(v)
                    for k, v in write.payload.items()
                    if k not in ("owner_task_id", "title") and v is not None
                }
                conv = ConversationRecord(
                    id=write.id,
                    owner_task_id=owner_id,
                    title=title,
                    metadata=metadata,
                    created_at=time.time(),
                )
                self._conversations[write.id] = conv
                if write.id not in self._conversation_entries:
                    self._conversation_entries[write.id] = []

            elif write.kind == StorageWriteKind.ENTRY:
                conv_id = str(write.payload.get("conversation_id", ""))
                kind = str(write.payload.get("kind", "message"))
                payload_data = dict(write.payload)
                payload_data.pop("conversation_id", None)
                payload_data.pop("kind", None)

                entry = EntryRecord(
                    id=write.id,
                    conversation_id=conv_id,
                    seq=seq,
                    kind=kind,
                    payload=payload_data,
                    created_at=time.time(),
                )
                self._entries[write.id] = entry
                if conv_id not in self._conversation_entries:
                    self._conversation_entries[conv_id] = []
                self._conversation_entries[conv_id].append(write.id)

            elif write.kind == StorageWriteKind.TASK:
                conv_id = str(write.payload.get("conversation_id", ""))
                kind = str(write.payload.get("kind", "task"))
                status = str(write.payload.get("status", "pending"))
                abort_req = bool(write.payload.get("abort_requested", False))
                checkpoint = dict(write.payload)
                for k in ("conversation_id", "kind", "status", "abort_requested"):
                    checkpoint.pop(k, None)

                task = TaskRecord(
                    id=write.id,
                    conversation_id=conv_id,
                    kind=kind,
                    status=status,
                    checkpoint=checkpoint,
                    abort_requested=abort_req,
                    updated_at=time.time(),
                )
                self._tasks[write.id] = task

            elif write.kind == StorageWriteKind.DOCUMENT:
                version = int(write.payload.get("version", 1))
                content = dict(write.payload)
                content.pop("version", None)

                doc = DocumentRecord(
                    id=write.id,
                    version=version,
                    content=content,
                    updated_at=time.time(),
                )
                self._documents[write.id] = doc

        return seq

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        return self._conversations.get(conversation_id)

    def get_entry(self, entry_id: str) -> EntryRecord | None:
        return self._entries.get(entry_id)

    def list_entries(
        self,
        conversation_id: str,
        limit: int = 100,
        after_seq: int = 0,
    ) -> Sequence[EntryRecord]:
        entry_ids = self._conversation_entries.get(conversation_id, [])
        results: list[EntryRecord] = []
        for eid in entry_ids:
            ent = self._entries.get(eid)
            if ent is not None and ent.seq > after_seq:
                results.append(ent)
                if len(results) >= limit:
                    break
        return results

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self._documents.get(document_id)

    def get_current_seq(self) -> int:
        return self._current_seq

    def reopen(self) -> None:
        """Simulate reopening by deep-copying stored records."""
        self._conversations = copy.deepcopy(self._conversations)
        self._entries = copy.deepcopy(self._entries)
        self._conversation_entries = copy.deepcopy(self._conversation_entries)
        self._tasks = copy.deepcopy(self._tasks)
        self._documents = copy.deepcopy(self._documents)

    def close(self) -> None:
        """No-op for in-memory backend."""
        pass
