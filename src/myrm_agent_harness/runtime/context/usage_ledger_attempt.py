"""Attempt-level usage ledger with adjustment records implementing Pi Harness v2 specification.

Implements the Pi Harness v2 cost durability architecture:
1. Cost Durability Independent of Result Durability:
   Every provider request settles with an attempt-level usage record before any
   classification, retry, or discard ("A failed attempt's id never materializes,
   which is the point").
2. Multi-Cause Categorization:
   assistant, compaction, branch_summary, deferred_fetch, tool, hook, adjustment.
3. Entry-Bound Read-Time Cost Aggregation:
   Effective cost of an entry is a read-time sum of all usage records bound to its
   provisioned entry_id (base + failed attempts + tool overhead + adjustments).
4. Reconciliation Adjustments:
   Supports signed adjustment records (positive or negative) anytime for external
   auditing and price reconciliation.

[INPUT]
- entry_id: str | None
- run_id: str | None
- attempt: int
- cause: UsageCause
- prompt_tokens: int
- completion_tokens: int
- cost_usd: float

[OUTPUT]
- UsageCause
- AttemptUsageItem
- EffectiveEntryCost
- SessionUsageRollup
- AttemptUsageLedger

[POS]
Harness runtime context layer. Delivers audit-grade attempt billing, adjustment
reconciliation, and entry-level cost rollups.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class UsageCause(StrEnum):
    """Discriminant causes for token spend."""

    ASSISTANT = "assistant"
    COMPACTION = "compaction"
    BRANCH_SUMMARY = "branch_summary"
    DEFERRED_FETCH = "deferred_fetch"
    TOOL = "tool"
    HOOK = "hook"
    ADJUSTMENT = "adjustment"


@dataclass(slots=True, frozen=True)
class AttemptUsageItem:
    """A durable usage measurement for a single attempt or adjustment."""

    record_id: str
    cause: UsageCause
    entry_id: str | None = None
    run_id: str | None = None
    attempt: int = 1
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    stop_reason: str | None = None
    timestamp_ms: int = 0
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Convert item to JSON-serializable dictionary."""
        return {
            "record_id": self.record_id,
            "cause": self.cause.value,
            "entry_id": self.entry_id,
            "run_id": self.run_id,
            "attempt": self.attempt,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "stop_reason": self.stop_reason,
            "timestamp_ms": self.timestamp_ms,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AttemptUsageItem:
        """Construct item from dictionary."""
        det_raw = data.get("details")
        det_dict: dict[str, str] = (
            {str(k): str(v) for k, v in det_raw.items()}
            if isinstance(det_raw, dict)
            else {}
        )
        return cls(
            record_id=str(data["record_id"]),
            cause=UsageCause(str(data["cause"])),
            entry_id=str(data["entry_id"]) if data.get("entry_id") is not None else None,
            run_id=str(data["run_id"]) if data.get("run_id") is not None else None,
            attempt=int(str(data.get("attempt", 1))),
            model=str(data.get("model", "")),
            prompt_tokens=int(str(data.get("prompt_tokens", 0))),
            completion_tokens=int(str(data.get("completion_tokens", 0))),
            total_tokens=int(str(data.get("total_tokens", 0))),
            cost_usd=float(str(data.get("cost_usd", 0.0))),
            stop_reason=str(data["stop_reason"]) if data.get("stop_reason") is not None else None,
            timestamp_ms=int(str(data.get("timestamp_ms", 0))),
            details=det_dict,
        )


@dataclass(slots=True, frozen=True)
class EffectiveEntryCost:
    """Read-time aggregation of all attempts and adjustments bound to an entry."""

    entry_id: str
    total_tokens: int
    total_cost_usd: float
    attempt_count: int
    adjustment_cost_usd: float
    records: tuple[AttemptUsageItem, ...]


@dataclass(slots=True, frozen=True)
class SessionUsageRollup:
    """Session-level spend rollup across all attempts and adjustments."""

    total_tokens: int
    total_cost_usd: float
    total_records: int
    tokens_by_cause: dict[str, int]
    cost_by_model: dict[str, float]
    net_adjustment_usd: float


class AttemptUsageLedger:
    """Thread-safe append-only ledger supporting attempt-level billing and adjustments."""

    def __init__(self, journal_path: Path | str | None = None) -> None:
        self._journal_path = Path(journal_path) if journal_path is not None else None
        self._lock = threading.RLock()
        self._records: list[AttemptUsageItem] = []
        self._by_entry: dict[str, list[AttemptUsageItem]] = defaultdict(list)

        if self._journal_path and self._journal_path.exists():
            self._resurrect_from_journal()

    def _append_to_disk(self, item: AttemptUsageItem) -> None:
        """Append item to physical journal file."""
        if self._journal_path is None:
            return
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(item.to_dict(), ensure_ascii=False) + "\n"
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _resurrect_from_journal(self) -> None:
        """Reconstruct state from physical journal file on disk."""
        if self._journal_path is None or not self._journal_path.exists():
            return

        with self._journal_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                    item = AttemptUsageItem.from_dict(data)
                    self._records.append(item)
                    if item.entry_id:
                        self._by_entry[item.entry_id].append(item)
                except Exception:
                    continue

    def record_attempt(
        self,
        *,
        cause: UsageCause,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        entry_id: str | None = None,
        run_id: str | None = None,
        attempt: int = 1,
        stop_reason: str | None = None,
        details: dict[str, str] | None = None,
    ) -> AttemptUsageItem:
        """Record usage settled by an attempt, regardless of whether it succeeded or was discarded."""
        tot = prompt_tokens + completion_tokens
        item = AttemptUsageItem(
            record_id=f"usg-{uuid.uuid4().hex[:12]}",
            cause=cause,
            entry_id=entry_id,
            run_id=run_id,
            attempt=attempt,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=tot,
            cost_usd=cost_usd,
            stop_reason=stop_reason,
            timestamp_ms=int(time.time() * 1000),
            details=dict(details or {}),
        )

        with self._lock:
            self._append_to_disk(item)
            self._records.append(item)
            if entry_id:
                self._by_entry[entry_id].append(item)

        return item

    def record_adjustment(
        self,
        *,
        cost_usd: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        entry_id: str | None = None,
        run_id: str | None = None,
        reason: str = "",
    ) -> AttemptUsageItem:
        """Record an out-of-band price reconciliation adjustment (supports signed values)."""
        return self.record_attempt(
            cause=UsageCause.ADJUSTMENT,
            model="adjustment",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            entry_id=entry_id,
            run_id=run_id,
            details={"adjustment_reason": reason},
        )

    def get_effective_cost(self, entry_id: str) -> EffectiveEntryCost:
        """Query read-time effective cost bound to a specific entry (including failed attempts & adjustments)."""
        with self._lock:
            items = tuple(self._by_entry.get(entry_id, []))
            tot_tokens = sum(it.total_tokens for it in items)
            tot_cost = sum(it.cost_usd for it in items)
            attempts = sum(1 for it in items if it.cause != UsageCause.ADJUSTMENT)
            adj_cost = sum(it.cost_usd for it in items if it.cause == UsageCause.ADJUSTMENT)

            return EffectiveEntryCost(
                entry_id=entry_id,
                total_tokens=tot_tokens,
                total_cost_usd=round(tot_cost, 6),
                attempt_count=attempts,
                adjustment_cost_usd=round(adj_cost, 6),
                records=items,
            )

    def get_session_rollup(self) -> SessionUsageRollup:
        """Query full session spend across all attempts, retries, and adjustments."""
        with self._lock:
            tot_tokens = 0
            tot_cost = 0.0
            by_cause: dict[str, int] = defaultdict(int)
            by_model: dict[str, float] = defaultdict(float)
            net_adj = 0.0

            for it in self._records:
                tot_tokens += it.total_tokens
                tot_cost += it.cost_usd
                by_cause[it.cause.value] += it.total_tokens
                if it.model:
                    by_model[it.model] += it.cost_usd
                if it.cause == UsageCause.ADJUSTMENT:
                    net_adj += it.cost_usd

            return SessionUsageRollup(
                total_tokens=tot_tokens,
                total_cost_usd=round(tot_cost, 6),
                total_records=len(self._records),
                tokens_by_cause=dict(by_cause),
                cost_by_model={m: round(c, 6) for m, c in by_model.items()},
                net_adjustment_usd=round(net_adj, 6),
            )

    @property
    def total_records_count(self) -> int:
        """Total number of logged usage attempts and adjustments."""
        with self._lock:
            return len(self._records)

    def get_records(self) -> tuple[AttemptUsageItem, ...]:
        """Return all logged usage attempts and adjustments immutably."""
        with self._lock:
            return tuple(self._records)
