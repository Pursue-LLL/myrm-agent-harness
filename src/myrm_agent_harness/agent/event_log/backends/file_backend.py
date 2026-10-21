"""FileEventLogBackend — JSONL file-based event persistence with crash durability.

Writes events as one JSON line per record, supporting all three
deployment modes (local / sandbox) with identical semantics.
Hardened with torn tail self-repair and short-write protection.

[INPUT]
- event_log.protocols::EventLogBackend, FlushableEventLogBackend
- event_log.durable_atomic_writer::DurableLogWriter

[OUTPUT]
- FileEventLogBackend: JSONL file storage with durable self-repairing appends

[POS]
Built-in reference backend. Thread-safe via asyncio.Lock and cross-process safe
via advisory file locking. Sequence-based deduplication for idempotent appends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from myrm_agent_harness.observability.invariants.bootstrap import ensure_runtime_invariants_installed
from myrm_agent_harness.observability.invariants.config import get_invariant_mode
from myrm_agent_harness.observability.invariants.registry import InvariantMode
from myrm_agent_harness.observability.metrics.event_log_metrics import (
    event_log_jsonl_line_downgraded_total,
)

from ..durable_atomic_writer import DurableLogWriter
from ..integrity_gate import assert_log_integrity
from ..types import EventFilter, EventPayload, StructuredEvent

logger = logging.getLogger(__name__)

_DEFAULT_MAX_JSONL_LINE_BYTES = 100 * 1024


def _utf8_byte_length(s: str) -> int:
    return len(s.encode("utf-8"))


def _iter_reverse_lines(file_obj: TextIO, buffer_size: int = 8192) -> Iterator[str]:
    """Yield non-empty lines from file_obj in reverse order from end to start.

    Skips any unterminated final line (uncommitted torn tail).
    """
    file_obj.seek(0, 2)
    file_size = file_obj.tell()
    if file_size == 0:
        return

    file_obj.seek(file_size - 1)
    has_trailing_newline = file_obj.read(1) == "\n"

    remainder = ""
    offset = file_size
    first_chunk = True
    while offset > 0:
        read_size = min(buffer_size, offset)
        offset -= read_size
        file_obj.seek(offset)
        chunk = file_obj.read(read_size) + remainder
        lines = chunk.split("\n")
        remainder = lines[0]
        valid_lines = lines[1:]
        if first_chunk:
            first_chunk = False
            if not has_trailing_newline and valid_lines:
                valid_lines.pop()
        for line in reversed(valid_lines):
            stripped = line.strip()
            if stripped:
                yield stripped
    if remainder.strip() and has_trailing_newline:
        yield remainder.strip()


def _jsonl_line_for_event(e: StructuredEvent, max_line_bytes: int) -> tuple[str, bool, int]:
    """Serialize one event to a JSONL line; downsize if over ``max_line_bytes``."""
    line = json.dumps(e.to_dict(), ensure_ascii=False) + "\n"
    n = _utf8_byte_length(line)
    if n <= max_line_bytes:
        return line, False, 0

    down = StructuredEvent(
        sequence=e.sequence,
        timestamp=e.timestamp,
        event_type=e.event_type,
        session_id=e.session_id,
        data=EventPayload(
            **{
                "_jsonl_oversized": True,
                "_original_serialized_bytes": n,
                "_max_line_bytes": max_line_bytes,
            }
        ),
    )
    down_dict = down.to_dict()
    down_line = json.dumps(down_dict, ensure_ascii=False) + "\n"
    if _utf8_byte_length(down_line) <= max_line_bytes:
        return down_line, True, n

    tight = json.dumps(down_dict, ensure_ascii=False, separators=(",", ":")) + "\n"
    if _utf8_byte_length(tight) <= max_line_bytes:
        return tight, True, n

    tiny_event = StructuredEvent(
        sequence=e.sequence,
        timestamp=e.timestamp,
        event_type=e.event_type,
        session_id=e.session_id,
        data=EventPayload(**{"_o": 1, "b": n, "m": max_line_bytes}),
    )
    last = json.dumps(tiny_event.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
    return last, True, n


class FileEventLogBackend:
    """JSONL file backend with sequence-based deduplication, torn tail repair, and retention."""

    def __init__(
        self,
        log_dir: Path,
        session_id: str,
        retention_days: int | None = None,
        *,
        max_jsonl_line_bytes: int = _DEFAULT_MAX_JSONL_LINE_BYTES,
        durable: bool = True,
        use_file_lock: bool = True,
    ) -> None:
        if max_jsonl_line_bytes < 64:
            raise ValueError("max_jsonl_line_bytes must be at least 64")
        self._log_dir = log_dir
        self._session_id = session_id
        self._lock = asyncio.Lock()
        self._max_seq = 0
        self._file_path = self._log_dir / f"{session_id}.jsonl"
        self._retention_days = retention_days if retention_days is not None else 30
        self._max_jsonl_line_bytes = max_jsonl_line_bytes
        self._writer = DurableLogWriter(
            self._file_path,
            durable=durable,
            use_file_lock=use_file_lock,
        )

    async def append(self, events: list[StructuredEvent]) -> None:
        if not events:
            return

        async with self._lock:
            self._log_dir.mkdir(parents=True, exist_ok=True)

            deduped = [e for e in events if e.sequence > self._max_seq]
            if not deduped:
                return

            lines: list[str] = []
            for e in deduped:
                line, downgraded, orig_bytes = _jsonl_line_for_event(e, self._max_jsonl_line_bytes)
                if downgraded:
                    logger.warning(
                        "jsonl_line_downgraded session_id=%s seq=%d event_type=%s "
                        "original_serialized_bytes=%d max_line_bytes=%d",
                        e.session_id,
                        e.sequence,
                        e.event_type,
                        orig_bytes,
                        self._max_jsonl_line_bytes,
                    )
                    if event_log_jsonl_line_downgraded_total is not None:
                        event_log_jsonl_line_downgraded_total.inc()
                lines.append(line)

            # Durable append with atomic self-repair and short-write protection
            await asyncio.to_thread(self._writer.append_lines, lines)
            self._max_seq = deduped[-1].sequence

    async def get_events(self, session_id: str, event_filter: EventFilter | None = None) -> list[StructuredEvent]:
        target_file = self._log_dir / f"{session_id}.jsonl"

        events: list[StructuredEvent] = []
        type_substrings: tuple[str, ...] | None = None
        if event_filter and event_filter.event_types:
            type_substrings = tuple(f'"{etype}"' for etype in event_filter.event_types)

        def _read_and_parse_events() -> list[StructuredEvent]:
            parsed: list[StructuredEvent] = []
            try:
                with target_file.open("r", encoding="utf-8") as f:
                    for raw_line in f:
                        # An unterminated final line is an uncommitted append, skipped on read
                        if not raw_line.endswith("\n"):
                            logger.debug("Skipping uncommitted unterminated final line in %s", target_file)
                            break

                        line = raw_line.strip()
                        if not line:
                            continue

                        # Fast pre-filtering: skip lines that cannot match target event types
                        if type_substrings is not None and not any(ts in line for ts in type_substrings):
                            continue

                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError:
                            logger.debug("Skipping malformed event line")
                            continue

                        event = StructuredEvent(
                            sequence=raw["seq"],
                            timestamp=raw["ts"],
                            event_type=raw["type"],
                            session_id=raw["sid"],
                            data=EventPayload(**raw.get("data", {})),
                        )

                        if event_filter and not _matches(event, event_filter):
                            continue
                        parsed.append(event)

                        if event_filter and event_filter.limit and len(parsed) >= event_filter.limit:
                            break
            except FileNotFoundError:
                return []
            return parsed

        async with self._lock:
            events = await asyncio.to_thread(_read_and_parse_events)

        mode = get_invariant_mode()
        if mode is not InvariantMode.DISABLED and events:
            ensure_runtime_invariants_installed()
            strict = mode is InvariantMode.STRICT
            assert_log_integrity(events, strict=strict)

        return events

    async def get_latest_custom_state(
        self,
        session_id: str,
        custom_type: str | None = None,
        max_sequence: int | None = None,
    ) -> dict[str, object]:
        """Retrieve the latest consolidated custom state for a session."""
        target_file = self._log_dir / f"{session_id}.jsonl"
        result: dict[str, object] = {}

        def _scan_latest_state() -> dict[str, object]:
            nonlocal result
            try:
                with target_file.open("r", encoding="utf-8") as f:
                    for line in _iter_reverse_lines(f):
                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if max_sequence is not None:
                            seq = raw.get("seq")
                            if isinstance(seq, int) and seq > max_sequence:
                                continue

                        if raw.get("type") != "custom":
                            continue

                        data = raw.get("data", {})
                        ctype = data.get("custom_type")
                        if not isinstance(ctype, str) or not ctype:
                            continue

                        raw_state = data.get("state")
                        state_dict: dict[str, object] = (
                            raw_state if isinstance(raw_state, dict) else {"value": raw_state}
                        )

                        if custom_type is not None:
                            if ctype == custom_type:
                                return state_dict
                        else:
                            if ctype not in result:
                                result[ctype] = state_dict
            except FileNotFoundError:
                return {}
            return result if custom_type is None else {}

        async with self._lock:
            return await asyncio.to_thread(_scan_latest_state)

    async def get_all_session_ids(self) -> list[str]:
        """Retrieve all session IDs by scanning .jsonl files in log_dir."""
        if not self._log_dir.exists():
            return []

        session_ids: list[str] = []
        for file_path in self._log_dir.glob("*.jsonl"):
            session_id = file_path.stem
            if session_id:
                session_ids.append(session_id)

        return sorted(session_ids)

    async def flush(self) -> None:
        """Acquire write lock to guarantee all in-flight appends have hit the filesystem."""
        async with self._lock:
            pass

    def get_session_log_path(self, session_id: str) -> Path | None:
        """Return the filesystem path to the session's jsonl file if it exists, else None."""
        target = self._log_dir / f"{session_id}.jsonl"
        return target if target.exists() else None

    async def remove_session_log(self, session_id: str) -> bool:
        """Delete one session's jsonl file when permanently deleted."""
        target = self._log_dir / f"{session_id}.jsonl"
        if target.resolve().parent != self._log_dir.resolve():
            raise ValueError(f"Event log session id resolves outside the log directory: {session_id!r}")

        async with self._lock:
            try:
                target.unlink()
            except FileNotFoundError:
                return False
            if session_id == self._session_id:
                self._max_seq = 0
        return True

    async def close(self) -> None:
        """End the current run: wait for in-flight appends, then reset the dedup watermark."""
        async with self._lock:
            self._max_seq = 0

    async def cleanup_old_logs(self) -> int:
        """Remove log files older than retention_days."""
        if not self._log_dir.exists():
            return 0

        cutoff_time = time.time() - (self._retention_days * 86400)
        deleted_count = 0

        async with self._lock:
            for file_path in self._log_dir.glob("*.jsonl"):
                try:
                    mtime = file_path.stat().st_mtime
                    if mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info(
                            "Deleted old event log: %s (age: %.1f days)",
                            file_path.name,
                            (time.time() - mtime) / 86400,
                        )
                except Exception as e:
                    logger.warning("Failed to delete old log %s: %s", file_path.name, e)
                    continue

        if deleted_count > 0:
            logger.info("Cleanup completed: %d old event logs deleted", deleted_count)

        return deleted_count


def _matches(event: StructuredEvent, f: EventFilter) -> bool:
    if f.event_types and event.event_type not in f.event_types:
        return False
    if f.start_time is not None and event.timestamp < f.start_time:
        return False
    if f.end_time is not None and event.timestamp > f.end_time:
        return False
    return not (f.start_sequence is not None and event.sequence < f.start_sequence)
