"""Session-scoped tool output spill store and bounded preview locator harness.

Implements DeepSeek-style spill capability family: automatically detects oversized
tool output, persists full artifacts to session-scoped storage, injects bounded previews
with canonical locator URIs, and supports on-demand range slicing.

[INPUT]
- runtime.context.session_spill_store_types::SpillPolicy, SpillProcessResult, SpillRecord,
  SpillSliceRequest, SpillSliceResult (POS: Type definitions for session-scoped tool output spill store and
  bounded preview locator.)

[OUTPUT]
- SessionScopedToolOutputSpillStore: Manages session-level tool output persistence, bounded preview
  generation, and on-demand retrieval.

[POS]
Session-scoped tool output spill store and bounded preview locator harness.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import uuid
from pathlib import Path

from myrm_agent_harness.runtime.context.session_spill_store_types import (
    SpillPolicy,
    SpillProcessResult,
    SpillRecord,
    SpillSliceRequest,
    SpillSliceResult,
)

logger = logging.getLogger(__name__)


class SessionScopedToolOutputSpillStore:
    """Manages session-level tool output persistence, bounded preview generation, and on-demand retrieval."""

    def __init__(self, default_policy: SpillPolicy | None = None) -> None:
        self._lock = threading.RLock()
        self._default_policy = default_policy or SpillPolicy()
        self._records: dict[str, SpillRecord] = {}  # locator_uri -> SpillRecord
        self._memory_cache: dict[str, str] = {}     # spill_id -> raw content

    def process_tool_output(
        self,
        session_id: str,
        tool_name: str,
        raw_output: str,
        policy: SpillPolicy | None = None,
    ) -> SpillProcessResult:
        """Inspect tool output against size policy; spill to storage if threshold is exceeded."""
        pol = policy or self._default_policy
        raw_bytes = raw_output.encode("utf-8")
        total_bytes = len(raw_bytes)
        token_estimate = max(1, len(raw_output) // 4)

        # 1. Check if output is within inline budget
        if total_bytes <= pol.max_inline_bytes and token_estimate <= pol.max_inline_tokens:
            return SpillProcessResult(
                is_spilled=False,
                content=raw_output,
                record=None,
                bytes_saved=0,
            )

        # 2. Threshold exceeded: trigger session spill
        spill_id = f"spill_{uuid.uuid4().hex[:12]}"
        locator_uri = f"spill://session/{session_id}/{spill_id}"
        file_path_str = f"{pol.base_storage_dir}/{session_id}/{spill_id}.txt"

        lines = raw_output.splitlines()
        total_lines = len(lines)

        # Best-effort file persistence
        try:
            spill_file = Path(file_path_str)
            spill_file.parent.mkdir(parents=True, exist_ok=True)
            spill_file.write_text(raw_output, encoding="utf-8")
        except OSError as err:
            logger.warning("Failed to persist spill to disk (%s), using in-memory store: %s", file_path_str, err)

        record = SpillRecord(
            spill_id=spill_id,
            session_id=session_id,
            tool_name=tool_name,
            file_path=file_path_str,
            total_bytes=total_bytes,
            total_lines=total_lines,
            locator_uri=locator_uri,
        )

        with self._lock:
            self._records[locator_uri] = record
            self._memory_cache[spill_id] = raw_output

        # 3. Generate bounded preview with locator token
        preview_content = self._render_bounded_preview(lines, record, pol)
        bytes_saved = max(0, total_bytes - len(preview_content.encode("utf-8")))

        logger.info(
            "Spilled %d bytes from tool '%s' to %s (saved %d bytes)",
            total_bytes,
            tool_name,
            locator_uri,
            bytes_saved,
        )

        return SpillProcessResult(
            is_spilled=True,
            content=preview_content,
            record=record,
            bytes_saved=bytes_saved,
        )

    def read_spill_slice(self, request: SpillSliceRequest) -> SpillSliceResult:
        """Retrieve an on-demand slice of lines from a spilled output artifact."""
        with self._lock:
            record = self._records.get(request.locator_uri)
            if record is None:
                raise KeyError(f"Spill locator not found: {request.locator_uri}")
            raw_content = self._memory_cache.get(record.spill_id)

        # Fallback to reading from disk if memory cache was evicted
        if raw_content is None:
            try:
                raw_content = Path(record.file_path).read_text(encoding="utf-8")
                with self._lock:
                    self._memory_cache[record.spill_id] = raw_content
            except OSError as err:
                raise FileNotFoundError(f"Failed to load spilled file {record.file_path}: {err}") from err

        lines = raw_content.splitlines()
        total_lines = len(lines)

        start = max(1, request.start_line)
        end = min(total_lines, request.end_line)

        if start > total_lines or start > end:
            sliced_lines: list[str] = []
        else:
            sliced_lines = lines[start - 1 : end]

        formatted_slice: list[str] = [
            f"[Spill Slice: {request.locator_uri} | Lines {start}-{end} of {total_lines}]"
        ]
        for idx, line in enumerate(sliced_lines, start=start):
            formatted_slice.append(f"{idx:5d} | {line}")

        return SpillSliceResult(
            locator_uri=request.locator_uri,
            total_lines=total_lines,
            requested_start=request.start_line,
            requested_end=request.end_line,
            lines_returned=len(sliced_lines),
            content="\n".join(formatted_slice),
        )

    def cleanup_session_spills(self, session_id: str) -> int:
        """Purge all spill records and cached artifacts associated with a session."""
        with self._lock:
            to_remove = [
                uri for uri, rec in self._records.items() if rec.session_id == session_id
            ]
            for uri in to_remove:
                rec = self._records.pop(uri)
                self._memory_cache.pop(rec.spill_id, None)
                with contextlib.suppress(OSError):
                    Path(rec.file_path).unlink(missing_ok=True)

        logger.debug("Cleaned up %d spills for session %s", len(to_remove), session_id)
        return len(to_remove)

    def get_record(self, locator_uri: str) -> SpillRecord | None:
        """Fetch audit record for a given spill locator."""
        with self._lock:
            return self._records.get(locator_uri)

    def _render_bounded_preview(
        self,
        lines: list[str],
        record: SpillRecord,
        pol: SpillPolicy,
    ) -> str:
        """Construct structured head/tail preview with explicit spill descriptor headers."""
        head_n = min(len(lines), pol.preview_head_lines)
        tail_n = min(len(lines) - head_n, pol.preview_tail_lines)

        head_lines = lines[:head_n]
        tail_lines = lines[-tail_n:] if tail_n > 0 else []
        omitted_count = len(lines) - (head_n + len(tail_lines))

        parts: list[str] = [
            f"[Output spilled to protect context budget: {record.total_bytes} bytes, {record.total_lines} lines]",
            f"[Spill Locator: {record.locator_uri}]",
            f"[To read omitted lines, use spill_read(locator='{record.locator_uri}', start_line=..., end_line=...)]",
            "",
            f"--- HEAD PREVIEW (First {head_n} lines) ---",
        ]
        parts.extend(head_lines)

        if omitted_count > 0:
            parts.extend([
                "",
                f"... [{omitted_count} lines omitted; total {record.total_lines} lines] ...",
                "",
                f"--- TAIL PREVIEW (Last {len(tail_lines)} lines) ---",
            ])
            parts.extend(tail_lines)

        return "\n".join(parts)
