"""Durable deferred write manager implementing Pi Harness v2 abort-survive semantics.

Implements the Pi Harness v2 deferred writes specification:
1. Facts vs Intent:
   While steering and follow-ups carry conversational intent and die on abort,
   deferred writes carry facts (model switches, active tools, thinking levels,
   custom metadata).
2. Survives Abort:
   Deferred writes survive run abort and cancellation, guaranteed to be applied
   during abort reconciliation.
3. Durable at Acceptance:
   Every deferred write is persisted to the append-only journal before acceptance
   is resolved ("Accepted input is never lost").
4. Crash Resurrection:
   Unapplied deferred writes are automatically recovered from the journal across
   process restarts.

[INPUT]
- kind: DeferredFactKind
- payload: dict[str, str]
- run_id: str | None

[OUTPUT]
- DeferredFactKind
- DurableDeferredWriteItem
- AbortDeferredApplyResult
- DurableDeferredWriteManager

[POS]
Harness runtime context layer. Manages crash-safe mid-turn facts and configuration
updates that strictly survive abort and cancelation.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DeferredFactKind(StrEnum):
    """Categorization of facts and configurations deferred mid-turn."""

    MODEL_CONFIG = "model_config"
    THINKING_LEVEL = "thinking_level"
    ACTIVE_TOOLS = "active_tools"
    CUSTOM_ENTRY = "custom_entry"
    SYSTEM_LABEL = "system_label"


class DeferredWriteRecordType(StrEnum):
    """Journal log record types for deferred writes."""

    WRITE_DEFERRED = "write_deferred"
    WRITE_APPLIED = "write_applied"


@dataclass(slots=True, frozen=True)
class DurableDeferredWriteItem:
    """A durable fact mutation deferred until checkpoint or abort reconciliation."""

    write_id: str
    kind: DeferredFactKind
    payload: dict[str, str]
    run_id: str | None = None
    created_at_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        """Convert item to JSON-serializable dictionary."""
        return {
            "write_id": self.write_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "run_id": self.run_id,
            "created_at_ms": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DurableDeferredWriteItem:
        """Construct item from dictionary."""
        payload_raw = data.get("payload")
        payload_dict: dict[str, str] = (
            {str(k): str(v) for k, v in payload_raw.items()}
            if isinstance(payload_raw, dict)
            else {}
        )
        return cls(
            write_id=str(data["write_id"]),
            kind=DeferredFactKind(str(data["kind"])),
            payload=payload_dict,
            run_id=str(data["run_id"]) if data.get("run_id") is not None else None,
            created_at_ms=int(str(data.get("created_at_ms", 0))),
        )


@dataclass(slots=True, frozen=True)
class AbortDeferredApplyResult:
    """Summary of deferred facts preserved and committed during run abort."""

    run_id: str | None
    applied_count: int
    applied_items: tuple[DurableDeferredWriteItem, ...]
    survived: bool = True


class DurableDeferredWriteManager:
    """Thread-safe orchestrator managing deferred writes across checkpoints and aborts."""

    def __init__(self, journal_path: Path | str | None = None) -> None:
        self._journal_path = Path(journal_path) if journal_path is not None else None
        self._lock = threading.RLock()
        self._pending_writes: list[DurableDeferredWriteItem] = []

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
        """Scan journal to resurrect unapplied deferred writes."""
        if self._journal_path is None or not self._journal_path.exists():
            return

        enqueued_map: dict[str, DurableDeferredWriteItem] = {}
        applied_set: set[str] = set()

        with self._journal_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rec = json.loads(stripped)
                    rec_type = rec.get("record_type")
                    if rec_type == DeferredWriteRecordType.WRITE_DEFERRED.value:
                        item = DurableDeferredWriteItem.from_dict(rec["target"])
                        enqueued_map[item.write_id] = item
                    elif rec_type == DeferredWriteRecordType.WRITE_APPLIED.value:
                        wid = rec.get("write_id")
                        if isinstance(wid, str):
                            applied_set.add(wid)
                except Exception:
                    continue

        self._pending_writes.clear()
        for wid, item in enqueued_map.items():
            if wid not in applied_set:
                self._pending_writes.append(item)

    def defer_write(
        self,
        kind: DeferredFactKind,
        payload: dict[str, str],
        *,
        run_id: str | None = None,
    ) -> DurableDeferredWriteItem:
        """Durable acceptance: persists write_deferred record before returning."""
        item = DurableDeferredWriteItem(
            write_id=f"dw-{uuid.uuid4().hex[:12]}",
            kind=kind,
            payload=dict(payload),
            run_id=run_id,
            created_at_ms=int(time.time() * 1000),
        )

        with self._lock:
            # 1. Synchronously persist to journal
            self._append_journal_record({
                "record_type": DeferredWriteRecordType.WRITE_DEFERRED.value,
                "timestamp_ms": item.created_at_ms,
                "target": item.to_dict(),
            })

            # 2. Stage into pending writes
            self._pending_writes.append(item)

        return item

    def defer_model_change(self, model: str, *, run_id: str | None = None) -> DurableDeferredWriteItem:
        """Defer model configuration update."""
        return self.defer_write(DeferredFactKind.MODEL_CONFIG, {"model": model}, run_id=run_id)

    def defer_thinking_level(self, level: str, *, run_id: str | None = None) -> DurableDeferredWriteItem:
        """Defer thinking level change."""
        return self.defer_write(DeferredFactKind.THINKING_LEVEL, {"level": level}, run_id=run_id)

    def defer_active_tools(self, tools: list[str], *, run_id: str | None = None) -> DurableDeferredWriteItem:
        """Defer active tools change."""
        return self.defer_write(
            DeferredFactKind.ACTIVE_TOOLS,
            {"tools": json.dumps(tools)},
            run_id=run_id,
        )

    def defer_custom_entry(
        self,
        entry_type: str,
        data: dict[str, str],
        *,
        run_id: str | None = None,
    ) -> DurableDeferredWriteItem:
        """Defer custom fact entry."""
        merged = {"entry_type": entry_type, **data}
        return self.defer_write(DeferredFactKind.CUSTOM_ENTRY, merged, run_id=run_id)

    def apply_pending_writes(
        self,
        target_state: dict[str, str] | None = None,
    ) -> list[DurableDeferredWriteItem]:
        """Apply all pending writes at a checkpoint boundary."""
        with self._lock:
            if not self._pending_writes:
                return []

            applied = list(self._pending_writes)
            self._pending_writes.clear()
            now_ms = int(time.time() * 1000)

            for item in applied:
                self._append_journal_record({
                    "record_type": DeferredWriteRecordType.WRITE_APPLIED.value,
                    "timestamp_ms": now_ms,
                    "write_id": item.write_id,
                })
                if target_state is not None:
                    self._mutate_state(target_state, item)

            return applied

    def apply_on_abort(
        self,
        target_state: dict[str, str] | None = None,
        *,
        run_id: str | None = None,
    ) -> AbortDeferredApplyResult:
        """Guaranteed apply during abort reconciliation: facts survive abort!"""
        applied_items = self.apply_pending_writes(target_state)
        return AbortDeferredApplyResult(
            run_id=run_id,
            applied_count=len(applied_items),
            applied_items=tuple(applied_items),
            survived=True,
        )

    @staticmethod
    def _mutate_state(state: dict[str, str], item: DurableDeferredWriteItem) -> None:
        """Helper to mutate target state based on deferred write kind."""
        if item.kind == DeferredFactKind.MODEL_CONFIG:
            state["model"] = item.payload.get("model", "")
        elif item.kind == DeferredFactKind.THINKING_LEVEL:
            state["thinking_level"] = item.payload.get("level", "")
        elif item.kind == DeferredFactKind.ACTIVE_TOOLS:
            state["active_tools"] = item.payload.get("tools", "[]")
        elif item.kind == DeferredFactKind.CUSTOM_ENTRY:
            for k, v in item.payload.items():
                state[f"custom_{k}"] = v

    @property
    def pending_count(self) -> int:
        """Count of pending unapplied deferred writes."""
        with self._lock:
            return len(self._pending_writes)
