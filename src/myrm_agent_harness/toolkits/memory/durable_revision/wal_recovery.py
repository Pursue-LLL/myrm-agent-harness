"""Two-Phase Intent Write-Ahead Log (WAL) and crash-recovery engine."""

from __future__ import annotations

import json
import threading
import time
import zlib
from pathlib import Path
from typing import NamedTuple

from myrm_agent_harness.toolkits.memory.durable_revision.models import RevisionIntent


class RecoveryAuditReport(NamedTuple):
    """Result of scanning and recovering uncommitted or interrupted WAL records."""

    healed_intents: list[RevisionIntent]
    corrupted_intent_ids: list[str]
    total_scanned: int


def calculate_payload_crc32(key: str, content: str, tags: dict[str, str]) -> int:
    """Compute deterministic CRC32 checksum over the write payload tuple."""
    sorted_tags = sorted(tags.items())
    raw_bytes = json.dumps(
        {"k": key, "c": content, "t": sorted_tags},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return zlib.crc32(raw_bytes)


class TwoPhaseIntentWAL:
    """Crash-safe Write-Ahead Logging manager for memory mutation intents."""

    def __init__(self, wal_dir: Path | str | None = None) -> None:
        self._lock = threading.Lock()
        self._wal_dir = Path(wal_dir) if wal_dir else None
        if self._wal_dir:
            self._wal_dir.mkdir(parents=True, exist_ok=True)
            self._wal_file = self._wal_dir / "memory_mutation_intents.jsonl"
        else:
            self._wal_file = None

        # In-memory intent registry: intent_id -> RevisionIntent
        self._intents: dict[str, RevisionIntent] = {}

    def log_intent(self, intent: RevisionIntent) -> None:
        """Phase 1: Persist mutation intent with CRC32 verification before mutation."""
        with self._lock:
            self._intents[intent.intent_id] = intent
            if self._wal_file:
                record = intent.model_dump()
                with open(self._wal_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()

    def commit_intent(self, intent_id: str) -> bool:
        """Phase 2: Atomically mark the intent as committed after mutation succeeded."""
        with self._lock:
            intent = self._intents.get(intent_id)
            if not intent:
                return False
            intent.phase = "COMMITTED"
            if self._wal_file:
                with open(self._wal_file, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {"intent_id": intent_id, "phase": "COMMITTED", "ts": time.time()},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    f.flush()
            return True

    def fail_intent(self, intent_id: str, reason: str = "") -> bool:
        """Mark an intent as failed/quarantined."""
        with self._lock:
            intent = self._intents.get(intent_id)
            if not intent:
                return False
            intent.phase = "FAILED"
            if self._wal_file:
                with open(self._wal_file, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {"intent_id": intent_id, "phase": "FAILED", "reason": reason, "ts": time.time()},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    f.flush()
            return True

    def scan_and_recover(self) -> RecoveryAuditReport:
        """Scan WAL records on startup to self-heal pending writes and isolate corruptions."""
        with self._lock:
            if not self._wal_file or not self._wal_file.exists():
                # Recover from in-memory if file is absent
                healed: list[RevisionIntent] = []
                corrupted: list[str] = []
                for intent in self._intents.values():
                    if intent.phase == "PENDING":
                        expected_crc = calculate_payload_crc32(intent.key, intent.content, intent.tags)
                        if expected_crc == intent.checksum_crc32:
                            healed.append(intent)
                        else:
                            corrupted.append(intent.intent_id)
                return RecoveryAuditReport(
                    healed_intents=healed,
                    corrupted_intent_ids=corrupted,
                    total_scanned=len(self._intents),
                )

            # Reconstruct states from file lines
            loaded_intents: dict[str, dict[str, str | int | float | dict[str, str] | None]] = {}
            with open(self._wal_file, encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                        iid = str(data.get("intent_id", ""))
                        if not iid:
                            continue
                        if "content" in data:
                            loaded_intents[iid] = data
                        elif "phase" in data and iid in loaded_intents:
                            loaded_intents[iid]["phase"] = data["phase"]
                    except json.JSONDecodeError:
                        continue

            healed_list: list[RevisionIntent] = []
            corrupted_list: list[str] = []

            for iid, record in loaded_intents.items():
                try:
                    intent = RevisionIntent.model_validate(record)
                    self._intents[iid] = intent
                    if intent.phase == "PENDING":
                        expected_crc = calculate_payload_crc32(intent.key, intent.content, intent.tags)
                        if expected_crc == intent.checksum_crc32:
                            healed_list.append(intent)
                        else:
                            corrupted_list.append(iid)
                except Exception:
                    corrupted_list.append(iid)

            return RecoveryAuditReport(
                healed_intents=healed_list,
                corrupted_intent_ids=corrupted_list,
                total_scanned=len(loaded_intents),
            )
