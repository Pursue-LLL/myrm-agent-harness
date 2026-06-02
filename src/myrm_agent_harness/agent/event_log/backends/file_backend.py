"""FileEventLogBackend — JSONL file-based event persistence.

Writes events as one JSON line per record, supporting all three
deployment modes (local / sandbox) with identical semantics.

[INPUT]
- event_log.protocol::EventLogBackend (POS: Protocol contract. Framework provides FileEventLogBackend; business layer may extend with SQLite / PostgreSQL implementations.)

[OUTPUT]
- FileEventLogBackend: JSONL file storage implementation

[POS]
Built-in reference backend. Thread-safe via asyncio.Lock.
Sequence-based deduplication for idempotent appends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from myrm_agent_harness.observability.metrics.event_log_metrics import (
    event_log_jsonl_line_downgraded_total,
)

from ..types import EventFilter, EventPayload, StructuredEvent

logger = logging.getLogger(__name__)

# Single JSONL line limit (UTF-8 bytes, including trailing newline) — last line of defense
# after logger._cap_data_size (top-level strings only). Nested / list payloads can still
# blow up without this cap.
_DEFAULT_MAX_JSONL_LINE_BYTES = 100 * 1024


def _utf8_byte_length(s: str) -> int:
    return len(s.encode("utf-8"))


def _jsonl_line_for_event(
    e: StructuredEvent, max_line_bytes: int
) -> tuple[str, bool, int]:
    """Serialize one event to a JSONL line; downsize if over ``max_line_bytes``.

    Returns:
        (line_with_trailing_newline, was_downgraded, original_serialized_bytes_if_downgraded_else_0)
    """
    line = json.dumps(e.to_dict(), ensure_ascii=False) + "\n"
    n = _utf8_byte_length(line)
    if n <= max_line_bytes:
        return line, False, 0

    down = StructuredEvent(
        sequence=e.sequence,
        timestamp=e.timestamp,
        event_type=e.event_type,
        session_id=e.session_id,
        data=EventPayload(**{
            "_jsonl_oversized": True,
            "_original_serialized_bytes": n,
            "_max_line_bytes": max_line_bytes,
        }),
    )
    down_dict = down.to_dict()
    down_line = json.dumps(down_dict, ensure_ascii=False) + "\n"
    if _utf8_byte_length(down_line) <= max_line_bytes:
        return down_line, True, n

    # Tight JSON (large session_id is rare; huge ``data`` was the target case)
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
    """JSONL file backend with sequence-based deduplication and log retention."""

    def __init__(
        self,
        log_dir: Path,
        session_id: str,
        retention_days: int | None = None,
        *,
        max_jsonl_line_bytes: int = _DEFAULT_MAX_JSONL_LINE_BYTES,
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

            with self._file_path.open("a", encoding="utf-8") as f:
                f.writelines(lines)

            self._max_seq = deduped[-1].sequence

    async def get_events(self, session_id: str, event_filter: EventFilter | None = None) -> list[StructuredEvent]:
        target_file = self._log_dir / f"{session_id}.jsonl"
        if not target_file.exists():
            return []

        events: list[StructuredEvent] = []
        async with self._lock:
            with target_file.open("r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
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

                    # File is already session-specific (filename = session_id.jsonl)
                    # So we don't need to filter by session_id within the file
                    if event_filter and not _matches(event, event_filter):
                        continue
                    events.append(event)

                    if event_filter and event_filter.limit and len(events) >= event_filter.limit:
                        break

        return events

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

    async def close(self) -> None:
        pass

    async def cleanup_old_logs(self) -> int:
        """Remove log files older than retention_days.

        Returns:
            Number of files deleted
        """
        if not self._log_dir.exists():
            return 0

        cutoff_time = time.time() - (self._retention_days * 86400)  # 86400 seconds per day
        deleted_count = 0

        async with self._lock:
            for file_path in self._log_dir.glob("*.jsonl"):
                try:
                    # Check file modification time
                    mtime = file_path.stat().st_mtime
                    if mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info(
                            f"Deleted old event log: {file_path.name} (age: {(time.time() - mtime) / 86400:.1f} days)"
                        )
                except Exception as e:
                    logger.warning(f"Failed to delete old log {file_path.name}: {e}")
                    continue

        if deleted_count > 0:
            logger.info(f"Cleanup completed: {deleted_count} old event logs deleted")

        return deleted_count


def _matches(event: StructuredEvent, f: EventFilter) -> bool:
    if f.event_types and event.event_type not in f.event_types:
        return False
    if f.start_time is not None and event.timestamp < f.start_time:
        return False
    if f.end_time is not None and event.timestamp > f.end_time:
        return False
    return not (f.start_sequence is not None and event.sequence < f.start_sequence)
