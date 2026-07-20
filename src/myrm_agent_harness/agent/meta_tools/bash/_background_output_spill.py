"""Incremental vault spill for long-running background bash stdout/stderr.

[INPUT]
- runtime.execution_paths::ensure_context_dir_exists, get_workspace_relative_path (POS: context paths)

[OUTPUT]
- BackgroundOutputSpillWriter: Append-only log writer under .context/{session}/evicted/

[POS]
BSDL Core — mirrors foreground _output_eviction persistence for background jobs.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SPILL_LINE_THRESHOLD = 80


class BackgroundOutputSpillWriter:
    """Append redacted lines to a session-scoped spill file once output grows."""

    def __init__(self, *, session_id: str, job_id: str) -> None:
        self._session_id = session_id
        self._job_id = job_id
        self._line_count = 0
        self._rel_path: str | None = None
        self._abs_path: Path | None = None
        self._spill_active = False

    @property
    def vault_log_ref(self) -> str | None:
        return self._rel_path

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
        if self._rel_path is not None:
            return
        from myrm_agent_harness.runtime.execution_paths import (
            ensure_context_dir_exists,
            get_workspace_relative_path,
        )

        ensure_context_dir_exists(self._session_id, "evicted")
        safe_job = "".join(c if c.isalnum() else "_" for c in self._job_id)[:48]
        session_dir = ensure_context_dir_exists(self._session_id, "evicted")
        abs_path = Path(session_dir) / f"bg_{safe_job}.log"
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        self._abs_path = abs_path
        self._rel_path = get_workspace_relative_path(str(abs_path))


__all__ = ["BackgroundOutputSpillWriter"]
