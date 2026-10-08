# [INPUT]: ContextHealthConfig, PurgeReceipt
# [OUTPUT]: EphemeralAutoPurgeSentry
# [POS]: agent/context_management/context_health_dashboard/ephemeral_auto_purge_sentry.py

"""Ephemeral auto-purge sentry safely reclaiming session-isolated disk files and FTS5 vaults.

[INPUT]
- ContextHealthConfig, PurgeReceipt: Contract definitions.

[OUTPUT]
- EphemeralAutoPurgeSentry: Cleanup sentry deleting temporary session artifacts and FTS5 vaults safely.

[POS]
Garbage collection and storage hygiene layer for context health dashboard.
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Sequence

from .context_health_types import ContextHealthConfig, PurgeReceipt


class EphemeralAutoPurgeSentry:
    """Detects, inspects, and reclaims temporary session caches and SQLite vaults."""

    def __init__(self, config: ContextHealthConfig | None = None) -> None:
        self._config = config or ContextHealthConfig()

    def resolve_session_ephemeral_dir(self, session_id: str, base_root: str | None = None) -> str:
        """Resolves target directory path strictly bound to session_id."""
        template = self._config.base_ephemeral_dir_template
        rel_path = template.replace("{session_id}", session_id)
        if base_root:
            return os.path.abspath(os.path.join(base_root, rel_path))
        return os.path.abspath(rel_path)

    def scan_ephemeral_usage(self, session_id: str, base_root: str | None = None) -> tuple[int, int]:
        """Scans ephemeral session directory and returns (file_count, total_bytes)."""
        target_dir = self.resolve_session_ephemeral_dir(session_id, base_root)
        if not os.path.exists(target_dir) or not os.path.isdir(target_dir):
            return 0, 0

        file_count = 0
        total_bytes = 0

        for root, _, files in os.walk(target_dir):
            for f in files:
                f_path = os.path.join(root, f)
                try:
                    total_bytes += os.path.getsize(f_path)
                    file_count += 1
                except OSError:
                    pass

        return file_count, total_bytes

    def purge_session_ephemeral_storage(
        self,
        session_id: str,
        confirm: bool = True,
        base_root: str | None = None,
    ) -> PurgeReceipt:
        """Permanently deletes session ephemeral caches and temporary index databases."""
        start_time = time.perf_counter()
        target_dir = self.resolve_session_ephemeral_dir(session_id, base_root)

        if not confirm:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return PurgeReceipt(
                session_id=session_id,
                purged_files_count=0,
                reclaimed_bytes=0,
                duration_ms=round(duration_ms, 2),
                target_directory=target_dir,
                status="skipped_not_confirmed",
            )

        # Safety fence: prevent purging dangerous paths
        self._assert_safe_directory(target_dir, session_id)

        if not os.path.exists(target_dir):
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return PurgeReceipt(
                session_id=session_id,
                purged_files_count=0,
                reclaimed_bytes=0,
                duration_ms=round(duration_ms, 2),
                target_directory=target_dir,
                status="not_found",
            )

        file_count, total_bytes = self.scan_ephemeral_usage(session_id, base_root)

        try:
            shutil.rmtree(target_dir)
            status = "success"
        except OSError as exc:
            status = f"error: {exc}"

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return PurgeReceipt(
            session_id=session_id,
            purged_files_count=file_count,
            reclaimed_bytes=total_bytes,
            duration_ms=round(duration_ms, 2),
            target_directory=target_dir,
            status=status,
        )

    def _assert_safe_directory(self, target_dir: str, session_id: str) -> None:
        """Fails closed if the path appears root-level or disconnected from session_id."""
        normalized = os.path.normpath(target_dir)
        if normalized in ("/", "\\", ".", ""):
            raise ValueError(f"Dangerous purge target path intercepted: {target_dir}")
        if session_id not in normalized:
            raise ValueError(f"Target path does not contain session_id fence: {target_dir}")
