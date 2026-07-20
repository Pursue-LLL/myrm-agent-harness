"""Incremental vault spill for long-running background bash stdout/stderr.

[INPUT]
- runtime.execution_paths::ensure_context_dir_exists (POS: session-scoped context dirs)

[OUTPUT]
- BackgroundOutputSpillWriter: Append-only log writer; exposes evicted API basename via vault_log_ref

[POS]
Long-running background bash stdout/stderr spill under .context/{session}/evicted/ (same filename contract as foreground _output_eviction).
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_SPILL_LINE_THRESHOLD = 80
_EVICTED_BASENAME_PREFIX = "output_"
_EVICTED_BASENAME_SUFFIX = ".txt"


class BackgroundOutputSpillWriter:
    """Append redacted lines to a session-scoped spill file once output grows."""

    def __init__(self, *, session_id: str, job_id: str) -> None:
        self._session_id = session_id
        self._job_id = job_id
        self._line_count = 0
        self._filename: str | None = None
        self._abs_path: Path | None = None
        self._spill_active = False

    @property
    def vault_log_ref(self) -> str | None:
        """Basename for /files/evicted API (matches foreground _output_eviction)."""
        if self._filename is None:
            return None
        return self._filename

    def append_line(self, stream: str, text: str) -> None:
        if not self._session_id or not text:
            return
        self._line_count += 1
        if not self._spill_active and self._line_count < _SPILL_LINE_THRESHOLD:
            return
        self._ensure_paths()
        if self._abs_path is None:
            return
        try:
            prefix = "[stderr] " if stream == "stderr" else ""
            with self._abs_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{prefix}{text}\n")
            self._spill_active = True
        except OSError as exc:
            logger.warning("Background spill write failed job=%s: %s", self._job_id, exc)

    def _ensure_paths(self) -> None:
        if self._filename is not None:
            return
        from myrm_agent_harness.runtime.execution_paths import ensure_context_dir_exists

        file_id = uuid4().hex[:8]
        filename = f"{_EVICTED_BASENAME_PREFIX}{file_id}{_EVICTED_BASENAME_SUFFIX}"
        session_dir = ensure_context_dir_exists(self._session_id, "evicted")
        abs_path = Path(session_dir) / filename
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        self._abs_path = abs_path
        self._filename = filename


__all__ = ["BackgroundOutputSpillWriter"]
