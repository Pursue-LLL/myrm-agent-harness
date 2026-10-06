"""Durable tri-queue engine (steer / followUp / nextRun) with abort divergence.

Implements the Pi Harness v2 durability and queue specification:
1. Three distinct queues:
   - steer: Mid-run steering corrections, consumed between turns. Aborted on run abort.
   - followUp: Sequential follow-up intent, consumed when tools and steering are idle.
               Aborted on run abort.
   - nextRun: Seeds the next run. Survives abort completely!
2. Durable acceptance:
   Every item is logged to an append-only journal before acceptance is confirmed
   ("Accepted input is never lost").
3. Durable retraction (cancelQueued):
   Unconsumed items can be revoked, persisting a cancellation marker.
4. Crash resurrection:
   Scans the journal to restore active unconsumed items across process crashes.

[INPUT]
- payload: str
- queue_type: QueueType
- run_id: str | None

[OUTPUT]
- QueueType
- QueueCoalesceMode
- ProvisionedQueueItem
- AbortOutcome
- DurableTriQueueManager

[POS]
Harness runtime context layer. Manages lane-level concurrent message dispatch,
crash-safe queue resurrection, and abort semantics divergence.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class QueueType(StrEnum):
    """The three specialized message queues."""

    STEER = "steer"
    FOLLOW_UP = "follow_up"
    NEXT_RUN = "next_run"


class QueueCoalesceMode(StrEnum):
    """Aggregation mode when multiple items are pending in a queue."""

    ALL = "all"
    COALESCE = "coalesce"


class QueueRecordType(StrEnum):
    """Journal log record types."""

    ENQUEUED = "queue_enqueued"
    CANCELLED = "queue_cancelled"
    CONSUMED = "queue_consumed"
    ABORTED = "abort_requested"


@dataclass(slots=True, frozen=True)
class ProvisionedQueueItem:
    """A durable enqueued item with a provisioned identity."""

    entry_id: str
    queue_type: QueueType
    payload: str
    run_id: str | None = None
    enqueued_at_ms: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Convert item to JSON-serializable dictionary."""
        return {
            "entry_id": self.entry_id,
            "queue_type": self.queue_type.value,
            "payload": self.payload,
            "run_id": self.run_id,
            "enqueued_at_ms": self.enqueued_at_ms,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProvisionedQueueItem:
        """Construct item from dictionary."""
        meta_raw = data.get("metadata")
        meta_dict: dict[str, str] = (
            {str(k): str(v) for k, v in meta_raw.items()}
            if isinstance(meta_raw, dict)
            else {}
        )
        return cls(
            entry_id=str(data["entry_id"]),
            queue_type=QueueType(str(data["queue_type"])),
            payload=str(data["payload"]),
            run_id=str(data["run_id"]) if data.get("run_id") is not None else None,
            enqueued_at_ms=int(str(data.get("enqueued_at_ms", 0))),
            metadata=meta_dict,
        )


@dataclass(slots=True, frozen=True)
class AbortOutcome:
    """Summary of items purged or preserved during run abort."""

    run_id: str | None
    aborted_steer_payloads: tuple[str, ...]
    aborted_followup_payloads: tuple[str, ...]
    survived_next_run_count: int


class DurableTriQueueManager:
    """Thread-safe orchestrator for steer, followUp, and nextRun queues."""

    def __init__(self, journal_path: Path | str | None = None) -> None:
        self._journal_path = Path(journal_path) if journal_path is not None else None
        self._lock = threading.Lock()
        self._steer_queue: list[ProvisionedQueueItem] = []
        self._followup_queue: list[ProvisionedQueueItem] = []
        self._next_run_queue: list[ProvisionedQueueItem] = []

        if self._journal_path and self._journal_path.exists():
            self._resurrect_from_journal()

    def _append_journal_record(self, record: dict[str, object]) -> None:
        """Write an append-only journal record if journal path is configured."""
        if self._journal_path is None:
            return
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _resurrect_from_journal(self) -> None:
        """Replay journal records to resurrect unconsumed queue state."""
        if self._journal_path is None or not self._journal_path.exists():
            return

        enqueued_map: dict[str, ProvisionedQueueItem] = {}
        consumed_or_cancelled: set[str] = set()

        with self._journal_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rec = json.loads(stripped)
                    rec_type = rec.get("record_type")
                    if rec_type == QueueRecordType.ENQUEUED.value:
                        item = ProvisionedQueueItem.from_dict(rec["target"])
                        enqueued_map[item.entry_id] = item
                    elif rec_type in (
                        QueueRecordType.CANCELLED.value,
                        QueueRecordType.CONSUMED.value,
                    ):
                        eid = rec.get("entry_id")
                        if isinstance(eid, str):
                            consumed_or_cancelled.add(eid)
                    elif rec_type == QueueRecordType.ABORTED.value:
                        # On abort record, steer & follow_up items before this point are invalidated
                        aborted_ids = rec.get("aborted_entry_ids")
                        if isinstance(aborted_ids, list):
                            for aid in aborted_ids:
                                if isinstance(aid, str):
                                    consumed_or_cancelled.add(aid)
                except Exception:
                    continue

        self._steer_queue.clear()
        self._followup_queue.clear()
        self._next_run_queue.clear()

        for eid, item in enqueued_map.items():
            if eid in consumed_or_cancelled:
                continue
            if item.queue_type == QueueType.STEER:
                self._steer_queue.append(item)
            elif item.queue_type == QueueType.FOLLOW_UP:
                self._followup_queue.append(item)
            elif item.queue_type == QueueType.NEXT_RUN:
                self._next_run_queue.append(item)

    def enqueue(
        self,
        queue_type: QueueType,
        payload: str,
        *,
        run_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ProvisionedQueueItem:
        """Durable acceptance: persists queue_enqueued record before returning."""
        item = ProvisionedQueueItem(
            entry_id=f"qitem-{uuid.uuid4().hex[:12]}",
            queue_type=queue_type,
            payload=payload,
            run_id=run_id,
            enqueued_at_ms=int(time.time() * 1000),
            metadata=dict(metadata or {}),
        )

        with self._lock:
            # 1. Synchronously persist acceptance to journal
            self._append_journal_record({
                "record_type": QueueRecordType.ENQUEUED.value,
                "timestamp_ms": item.enqueued_at_ms,
                "target": item.to_dict(),
            })

            # 2. Add to active in-memory queue
            if queue_type == QueueType.STEER:
                self._steer_queue.append(item)
            elif queue_type == QueueType.FOLLOW_UP:
                self._followup_queue.append(item)
            elif queue_type == QueueType.NEXT_RUN:
                self._next_run_queue.append(item)

        return item

    def steer(self, payload: str, *, run_id: str | None = None) -> ProvisionedQueueItem:
        """Enqueue steering note targeting the active run."""
        return self.enqueue(QueueType.STEER, payload, run_id=run_id)

    def follow_up(self, payload: str, *, run_id: str | None = None) -> ProvisionedQueueItem:
        """Enqueue follow-up note for subsequent idle continuation."""
        return self.enqueue(QueueType.FOLLOW_UP, payload, run_id=run_id)

    def next_run(self, payload: str, *, metadata: dict[str, str] | None = None) -> ProvisionedQueueItem:
        """Enqueue next-run seed message surviving run aborts."""
        return self.enqueue(QueueType.NEXT_RUN, payload, metadata=metadata)

    def cancel_queued(self, entry_id: str) -> bool:
        """Durably retract an unconsumed item by entry_id."""
        with self._lock:
            target_item: ProvisionedQueueItem | None = None
            for queue in (self._steer_queue, self._followup_queue, self._next_run_queue):
                for idx, item in enumerate(queue):
                    if item.entry_id == entry_id:
                        target_item = queue.pop(idx)
                        break
                if target_item is not None:
                    break

            if target_item is None:
                return False

            self._append_journal_record({
                "record_type": QueueRecordType.CANCELLED.value,
                "timestamp_ms": int(time.time() * 1000),
                "entry_id": entry_id,
            })
            return True

    def _consume_from_queue(
        self,
        queue: list[ProvisionedQueueItem],
        mode: QueueCoalesceMode,
    ) -> list[ProvisionedQueueItem]:
        """Internal helper to pop items and persist consumed records."""
        if not queue:
            return []

        popped = list(queue)
        queue.clear()
        now_ms = int(time.time() * 1000)

        for item in popped:
            self._append_journal_record({
                "record_type": QueueRecordType.CONSUMED.value,
                "timestamp_ms": now_ms,
                "entry_id": item.entry_id,
            })

        if mode == QueueCoalesceMode.COALESCE and len(popped) > 1:
            coalesced_text = "\n\n".join(it.payload for it in popped)
            last = popped[-1]
            return [
                ProvisionedQueueItem(
                    entry_id=last.entry_id,
                    queue_type=last.queue_type,
                    payload=coalesced_text,
                    run_id=last.run_id,
                    enqueued_at_ms=last.enqueued_at_ms,
                    metadata=last.metadata,
                )
            ]
        return popped

    def consume_steer(
        self,
        mode: QueueCoalesceMode = QueueCoalesceMode.ALL,
    ) -> list[ProvisionedQueueItem]:
        """Consume pending steering items."""
        with self._lock:
            return self._consume_from_queue(self._steer_queue, mode)

    def consume_followup(
        self,
        mode: QueueCoalesceMode = QueueCoalesceMode.ALL,
    ) -> list[ProvisionedQueueItem]:
        """Consume pending follow-up items."""
        with self._lock:
            return self._consume_from_queue(self._followup_queue, mode)

    def consume_next_run(
        self,
        mode: QueueCoalesceMode = QueueCoalesceMode.ALL,
    ) -> list[ProvisionedQueueItem]:
        """Consume pending next-run items."""
        with self._lock:
            return self._consume_from_queue(self._next_run_queue, mode)

    def abort_run(self, run_id: str | None = None) -> AbortOutcome:
        """Divergent abort semantics: steer and followUp die; nextRun survives!"""
        with self._lock:
            aborted_steers = tuple(item.payload for item in self._steer_queue)
            aborted_followups = tuple(item.payload for item in self._followup_queue)
            aborted_ids = [item.entry_id for item in self._steer_queue + self._followup_queue]

            self._steer_queue.clear()
            self._followup_queue.clear()

            self._append_journal_record({
                "record_type": QueueRecordType.ABORTED.value,
                "timestamp_ms": int(time.time() * 1000),
                "run_id": run_id,
                "aborted_entry_ids": aborted_ids,
            })

            return AbortOutcome(
                run_id=run_id,
                aborted_steer_payloads=aborted_steers,
                aborted_followup_payloads=aborted_followups,
                survived_next_run_count=len(self._next_run_queue),
            )

    def drain_for_checkpoint(
        self,
        *,
        has_active_tools: bool = False,
        steer_mode: QueueCoalesceMode = QueueCoalesceMode.ALL,
        followup_mode: QueueCoalesceMode = QueueCoalesceMode.ALL,
    ) -> tuple[list[str], list[str]]:
        """Order-sensitive checkpoint drain: steer first, followUp only when tools & steer exhausted."""
        with self._lock:
            steer_items = self._consume_from_queue(self._steer_queue, steer_mode)
            steer_payloads = [it.payload for it in steer_items]

            # Follow-up is strictly consumed when both tools and steer are exhausted
            followup_payloads: list[str] = []
            if not has_active_tools and not self._steer_queue and not steer_payloads:
                followup_items = self._consume_from_queue(self._followup_queue, followup_mode)
                followup_payloads = [it.payload for it in followup_items]

            return steer_payloads, followup_payloads

    @property
    def pending_counts(self) -> dict[QueueType, int]:
        """Snapshot of pending items across all three queues."""
        with self._lock:
            return {
                QueueType.STEER: len(self._steer_queue),
                QueueType.FOLLOW_UP: len(self._followup_queue),
                QueueType.NEXT_RUN: len(self._next_run_queue),
            }
