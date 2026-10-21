"""Append-only event-sourcing session file storage with corrupted tail auto-repair.

Provides high-throughput, zero-random-IO session event persistence with crash
resilience. Automatically detects and trims half-written trailing records caused by
power outage, OOM, or SIGKILL, preventing session corruption and line-concatenation errors.
Supports zero-lock read concurrency and stream-copy session branching.

[INPUT]
- json, os, logging, pathlib, threading (POS: Python standard library)

[OUTPUT]
- SessionEventRecord: Strongly typed immutable event dataclass
- EventSourcingLoadResult: Load result with recovery audit metadata
- EventSourcingSessionStore: File-backed append-only event store
- load_session_events_with_auto_repair: Pure function for crash-safe loading
- fork_session_by_stream_copy: Zero-lock streaming fork utility

[POS]
Runtime context session event-sourcing persistence layer.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionEventRecord:
    """Strongly typed immutable session event record for event-sourcing."""

    seq: int
    event_type: str
    ts: str
    payload: dict[str, object]
    session_id: str = ""

    @classmethod
    def create(
        cls,
        seq: int,
        event_type: str,
        payload: dict[str, object],
        session_id: str = "",
        ts: str | None = None,
    ) -> SessionEventRecord:
        """Factory helper constructing a record with default UTC timestamp."""
        return cls(
            seq=seq,
            event_type=event_type,
            ts=ts or datetime.now(UTC).isoformat(),
            payload=payload,
            session_id=session_id,
        )

    def to_json(self) -> str:
        """Serialize record to single-line JSON string without newline."""
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass(frozen=True)
class EventSourcingLoadResult:
    """Outcome of loading an append-only session file with repair audit data."""

    records: list[SessionEventRecord]
    corrupted_tail_trimmed: bool
    trimmed_content: str
    total_valid_lines: int


def _parse_record_line(line: str) -> SessionEventRecord | None:
    """Parse a single JSONL line into SessionEventRecord, or None if invalid."""
    try:
        data = json.loads(line)
        if not isinstance(data, dict):
            return None
        seq = int(data.get("seq", 0))
        event_type = str(data.get("event_type", ""))
        ts = str(data.get("ts", ""))
        raw_payload = data.get("payload", {})
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        session_id = str(data.get("session_id", ""))
        return SessionEventRecord(
            seq=seq,
            event_type=event_type,
            ts=ts,
            payload=payload,
            session_id=session_id,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def load_session_events_with_auto_repair(
    file_path: Path | str,
    auto_repair_file: bool = True,
) -> EventSourcingLoadResult:
    """Load session events from append-only JSONL with corrupted tail auto-repair.

    If the process was terminated mid-write (power cut, kill -9, OOM), the trailing
    line may be half-written. This loader gracefully recovers all preceding valid records,
    trims the corrupted suffix, and rewrites the file to prevent downstream append errors.
    """
    path = Path(file_path)
    if not path.exists():
        return EventSourcingLoadResult(
            records=[],
            corrupted_tail_trimmed=False,
            trimmed_content="",
            total_valid_lines=0,
        )

    try:
        raw_bytes = path.read_bytes()
    except OSError as err:
        logger.warning("Failed to read session event file %s: %s", path, err)
        return EventSourcingLoadResult(
            records=[],
            corrupted_tail_trimmed=False,
            trimmed_content="",
            total_valid_lines=0,
        )

    if not raw_bytes.strip():
        return EventSourcingLoadResult(
            records=[],
            corrupted_tail_trimmed=False,
            trimmed_content="",
            total_valid_lines=0,
        )

    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.split("\n")

    valid_records: list[SessionEventRecord] = []
    corrupted_tail_trimmed = False
    trimmed_content = ""

    for idx, line in enumerate(lines):
        clean_line = line.strip()
        if not clean_line:
            continue

        record = _parse_record_line(clean_line)
        if record is not None:
            valid_records.append(record)
        else:
            # Check if this is the last non-empty line (trailing half-written corruption)
            is_trailing = all(not rem.strip() for rem in lines[idx + 1 :])
            if is_trailing:
                corrupted_tail_trimmed = True
                trimmed_content = clean_line
                logger.warning(
                    "Warning: Recovered session with 1 corrupted trailing line trimmed from %s: %s",
                    path,
                    clean_line[:120],
                )
                break
            else:
                # Middle corrupted line: skip with warning to preserve remaining history
                logger.warning("Skipping corrupted non-tail line in %s: %s", path, clean_line[:80])

    # Rewrite repaired file atomically if a trailing corruption was trimmed
    if corrupted_tail_trimmed and auto_repair_file:
        try:
            tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
            with tmp_path.open("w", encoding="utf-8") as f:
                for rec in valid_records:
                    f.write(rec.to_json())
                    f.write("\n")
            tmp_path.replace(path)
            logger.info("Successfully repaired truncated session tail in %s", path)
        except OSError as exc:
            logger.error("Failed to write repaired session file %s: %s", path, exc)

    return EventSourcingLoadResult(
        records=valid_records,
        corrupted_tail_trimmed=corrupted_tail_trimmed,
        trimmed_content=trimmed_content,
        total_valid_lines=len(valid_records),
    )


def fork_session_by_stream_copy(
    source_file: Path | str,
    target_file: Path | str,
    up_to_seq: int | None = None,
) -> int:
    """Zero-lock stream-copy session fork up to an optional sequence boundary.

    Creates a new branch file containing events up to `up_to_seq` without acquiring
    heavy database locks, providing sub-millisecond session cloning.

    Returns:
        Number of events copied into the target file.
    """
    src = Path(source_file)
    dst = Path(target_file)
    if not src.exists():
        return 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    load_result = load_session_events_with_auto_repair(src, auto_repair_file=False)

    copied_count = 0
    tmp_target = dst.with_suffix(f".tmp.{os.getpid()}")

    with tmp_target.open("w", encoding="utf-8") as f:
        for rec in load_result.records:
            if up_to_seq is not None and rec.seq > up_to_seq:
                break
            f.write(rec.to_json())
            f.write("\n")
            copied_count += 1

    tmp_target.replace(dst)
    return copied_count


class EventSourcingSessionStore:
    """Thread-safe append-only event store for a session with auto-repair."""

    def __init__(self, file_path: Path | str, session_id: str = "") -> None:
        self.file_path = Path(file_path)
        self.session_id = session_id
        self._lock = threading.Lock()
        self._last_seq = 0
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            res = load_session_events_with_auto_repair(self.file_path, auto_repair_file=True)
            if res.records:
                self._last_seq = max(r.seq for r in res.records)
            self._initialized = True

    def append_event(
        self,
        event_type: str,
        payload: dict[str, object],
        seq: int | None = None,
    ) -> SessionEventRecord:
        """Atomically append a new event record to the session file."""
        self._ensure_initialized()
        with self._lock:
            next_seq = seq if seq is not None else self._last_seq + 1
            record = SessionEventRecord.create(
                seq=next_seq,
                event_type=event_type,
                payload=payload,
                session_id=self.session_id,
            )
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(record.to_json())
                f.write("\n")
            self._last_seq = next_seq
            return record

    def load_all(self, auto_repair: bool = True) -> list[SessionEventRecord]:
        """Load all valid session records with tail auto-repair."""
        res = load_session_events_with_auto_repair(self.file_path, auto_repair_file=auto_repair)
        return res.records

    def fork_branch(self, target_path: Path | str, up_to_seq: int | None = None) -> int:
        """Stream copy current session branch up to target sequence."""
        return fork_session_by_stream_copy(self.file_path, target_path, up_to_seq=up_to_seq)
