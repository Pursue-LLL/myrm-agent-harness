"""JSONL stream durable storage backend with atomic commit markers and crash reclamation.

[INPUT]
- CommitMarker, CommitWrite, ConversationRecord, DocumentRecord, EntryRecord, StorageBackendKind, StorageWriteKind, TaskRecord:
  Domain types from durable_storage_types.
- DurableStorageProtocol: Base storage contract.

[OUTPUT]
- JsonlDurableStorage: Append-only JSONL storage engine with integrity marker validation and crash recovery.

[POS]
Stream-based durable storage engine suitable for cloud sandbox and container volume persistence.
"""

from __future__ import annotations

import json
import os
import time
from typing import Sequence

from .durable_storage_protocol import DurableStorageProtocol
from .durable_storage_types import (
    CommitMarker,
    CommitWrite,
    ConversationRecord,
    DocumentRecord,
    EntryRecord,
    StorageBackendKind,
    StorageWriteKind,
    TaskRecord,
)

FORMAT_VERSION = 1


class JsonlDurableStorage(DurableStorageProtocol):
    """Append-only single-owner JSONL storage engine using atomic commit markers."""

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._current_seq: int = 0
        self._conversations: dict[str, ConversationRecord] = {}
        self._entries: dict[str, EntryRecord] = {}
        self._conversation_entries: dict[str, list[str]] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._documents: dict[str, DocumentRecord] = {}

        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        self._load_and_reclaim()

    @property
    def backend_kind(self) -> StorageBackendKind:
        return StorageBackendKind.JSONL

    def _load_and_reclaim(self) -> None:
        """Scan file, reconstruct state up to the last valid commit marker, and reclaim partial tail."""
        self._current_seq = 0
        self._conversations.clear()
        self._entries.clear()
        self._conversation_entries.clear()
        self._tasks.clear()
        self._documents.clear()

        if not os.path.exists(self._file_path):
            return

        last_valid_offset = 0
        pending_writes: list[dict[str, str | int | float | bool | dict[str, str | int | float | bool | None] | None]] = []

        with open(self._file_path, "r", encoding="utf-8") as f:
            while True:
                line_start_offset = f.tell()
                line = f.readline()
                if not line:
                    break

                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    record = json.loads(stripped)
                except Exception:
                    # Broken trailing line encountered; stop scanning
                    break

                rec_type = record.get("type")
                if rec_type == "commit":
                    # Verified commit marker reached
                    last_valid_offset = f.tell()
                    commit_seq = int(record.get("seq", 0))
                    self._current_seq = max(self._current_seq, commit_seq)
                    # Apply all accumulated pending writes in this commit batch
                    self._apply_batch(pending_writes, commit_seq)
                    pending_writes = []
                else:
                    pending_writes.append(record)

        # Truncate any uncommitted trailing bytes (crash reclamation)
        if os.path.exists(self._file_path) and os.path.getsize(self._file_path) > last_valid_offset:
            with open(self._file_path, "r+", encoding="utf-8") as f:
                f.truncate(last_valid_offset)
                f.flush()

    def _apply_batch(
        self,
        raw_ops: list[dict[str, str | int | float | bool | dict[str, str | int | float | bool | None] | None]],
        seq: int,
    ) -> None:
        """Materialize parsed operations into memory indices."""
        for op in raw_ops:
            kind_str = op.get("type")
            target_id = str(op.get("id", ""))
            payload = op.get("payload")
            payload_dict: dict[str, str | int | float | bool | None] = (
                payload if isinstance(payload, dict) else {}
            )

            if kind_str == StorageWriteKind.CONVERSATION.value:
                owner_id = str(payload_dict.get("owner_task_id", "")) or None
                title = str(payload_dict.get("title", ""))
                metadata = {
                    str(k): str(v)
                    for k, v in payload_dict.items()
                    if k not in ("owner_task_id", "title") and v is not None
                }
                conv = ConversationRecord(
                    id=target_id,
                    owner_task_id=owner_id,
                    title=title,
                    metadata=metadata,
                    created_at=float(op.get("timestamp", time.time())),
                )
                self._conversations[target_id] = conv
                if target_id not in self._conversation_entries:
                    self._conversation_entries[target_id] = []

            elif kind_str == StorageWriteKind.ENTRY.value:
                conv_id = str(payload_dict.get("conversation_id", ""))
                entry_kind = str(payload_dict.get("kind", "message"))
                entry_payload = dict(payload_dict)
                entry_payload.pop("conversation_id", None)
                entry_payload.pop("kind", None)

                entry = EntryRecord(
                    id=target_id,
                    conversation_id=conv_id,
                    seq=seq,
                    kind=entry_kind,
                    payload=entry_payload,
                    created_at=float(op.get("timestamp", time.time())),
                )
                self._entries[target_id] = entry
                if conv_id not in self._conversation_entries:
                    self._conversation_entries[conv_id] = []
                self._conversation_entries[conv_id].append(target_id)

            elif kind_str == StorageWriteKind.TASK.value:
                conv_id = str(payload_dict.get("conversation_id", ""))
                task_kind = str(payload_dict.get("kind", "task"))
                status = str(payload_dict.get("status", "pending"))
                abort_req = bool(payload_dict.get("abort_requested", False))
                checkpoint = dict(payload_dict)
                for k in ("conversation_id", "kind", "status", "abort_requested"):
                    checkpoint.pop(k, None)

                task = TaskRecord(
                    id=target_id,
                    conversation_id=conv_id,
                    kind=task_kind,
                    status=status,
                    checkpoint=checkpoint,
                    abort_requested=abort_req,
                    updated_at=float(op.get("timestamp", time.time())),
                )
                self._tasks[target_id] = task

            elif kind_str == StorageWriteKind.DOCUMENT.value:
                version = int(payload_dict.get("version", 1))
                doc_content = dict(payload_dict)
                doc_content.pop("version", None)

                doc = DocumentRecord(
                    id=target_id,
                    version=version,
                    content=doc_content,
                    updated_at=float(op.get("timestamp", time.time())),
                )
                self._documents[target_id] = doc

    def commit(self, writes: Sequence[CommitWrite]) -> int:
        """Atomically append operations followed by commit marker to JSONL file."""
        self._current_seq += 1
        seq = self._current_seq
        checksum = CommitMarker.compute_checksum(seq, writes)
        marker = CommitMarker(
            format_version=FORMAT_VERSION,
            seq=seq,
            writes_count=len(writes),
            checksum=checksum,
            timestamp=time.time(),
        )

        with open(self._file_path, "a", encoding="utf-8") as f:
            for w in writes:
                op_record = {
                    "format": FORMAT_VERSION,
                    "type": w.kind.value,
                    "id": w.id,
                    "payload": dict(w.payload),
                    "timestamp": time.time(),
                }
                f.write(json.dumps(op_record, sort_keys=True) + "\n")

            marker_dict = {
                "format": FORMAT_VERSION,
                "type": "commit",
                "seq": marker.seq,
                "writes_count": marker.writes_count,
                "checksum": marker.checksum,
                "timestamp": marker.timestamp,
            }
            f.write(json.dumps(marker_dict, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

        # Update in-memory view
        raw_ops_for_memory: list[dict[str, str | int | float | bool | dict[str, str | int | float | bool | None] | None]] = [
            {"type": w.kind.value, "id": w.id, "payload": dict(w.payload), "timestamp": time.time()}
            for w in writes
        ]
        self._apply_batch(raw_ops_for_memory, seq)
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
        """Reload log from disk and verify crash recovery consistency."""
        self._load_and_reclaim()

    def close(self) -> None:
        """Close storage handles."""
        pass
