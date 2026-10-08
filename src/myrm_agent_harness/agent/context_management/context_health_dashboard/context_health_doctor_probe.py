# [INPUT]: ContextHealthConfig, HealthDoctorDiagnosis
# [OUTPUT]: ContextHealthDoctorProbe
# [POS]: agent/context_management/context_health_dashboard/context_health_doctor_probe.py

"""Context health doctor probe diagnosing SQLite FTS5 capabilities, disk space, and write permissions.

[INPUT]
- ContextHealthConfig, HealthDoctorDiagnosis: Domain definitions.

[OUTPUT]
- ContextHealthDoctorProbe: Diagnostic probe inspecting runtime environment and storage health.

[POS]
Diagnostic and preflight health check layer for context health dashboard.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from typing import Sequence

from .context_health_types import ContextHealthConfig, HealthDoctorDiagnosis


class ContextHealthDoctorProbe:
    """Diagnoses FTS5 support, storage write permissions, and available disk headroom."""

    def __init__(self, config: ContextHealthConfig | None = None) -> None:
        self._config = config or ContextHealthConfig()

    def run_health_diagnosis(self, base_root: str | None = None) -> HealthDoctorDiagnosis:
        """Executes non-destructive preflight checks and produces health diagnosis."""
        recommendations: list[str] = []

        # 1. Test SQLite FTS5 Porter support
        fts5_supported = self._check_fts5_porter()
        if not fts5_supported:
            recommendations.append("Install or rebuild Python with SQLite FTS5 enabled.")

        # 2. Test SQLite FTS5 Trigram support
        trigram_supported = self._check_fts5_trigram()
        if not trigram_supported:
            recommendations.append("Upgrade SQLite to >=3.34.0 to enable FTS5 trigram tokenizer.")

        # 3. Test storage directory write permission
        target_root = base_root or os.getcwd()
        storage_writable = self._check_storage_writable(target_root)
        if not storage_writable:
            recommendations.append(f"Storage root '{target_root}' is not writable. Grant write permissions.")

        # 4. Check available disk space
        available_mb = self._get_available_disk_mb(target_root)
        if available_mb < 200:
            recommendations.append(f"Low disk space: {available_mb} MB available. Clean temporary files.")

        # 5. Detect orphaned session temporary files
        orphans = self._count_orphaned_directories(target_root)
        if orphans > 10:
            recommendations.append(f"Found {orphans} orphaned session folders. Run auto-purge sentry to reclaim disk.")

        is_healthy = fts5_supported and trigram_supported and storage_writable and (available_mb >= 100)

        return HealthDoctorDiagnosis(
            fts5_supported=fts5_supported,
            trigram_supported=trigram_supported,
            storage_writable=storage_writable,
            available_disk_mb=available_mb,
            orphaned_files_detected=orphans,
            is_healthy=is_healthy,
            remediation_recommendations=tuple(recommendations),
        )

    def _check_fts5_porter(self) -> bool:
        try:
            con = sqlite3.connect(":memory:")
            con.execute("CREATE VIRTUAL TABLE t_p USING fts5(content, tokenize='porter');")
            con.close()
            return True
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return False

    def _check_fts5_trigram(self) -> bool:
        try:
            con = sqlite3.connect(":memory:")
            con.execute("CREATE VIRTUAL TABLE t_tri USING fts5(content, tokenize='trigram');")
            con.close()
            return True
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return False

    def _check_storage_writable(self, path: str) -> bool:
        try:
            os.makedirs(path, exist_ok=True)
            test_file = os.path.join(path, f".write_test_{os.getpid()}.tmp")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test_file)
            return True
        except OSError:
            return False

    def _get_available_disk_mb(self, path: str) -> int:
        try:
            total, used, free = shutil.disk_usage(path)
            return free // (1024 * 1024)
        except OSError:
            return 1024  # Default fallback if disk_usage cannot be determined

    def _count_orphaned_directories(self, base_root: str) -> int:
        context_base = os.path.join(base_root, ".context")
        if not os.path.exists(context_base) or not os.path.isdir(context_base):
            return 0
        try:
            entries = os.listdir(context_base)
            return len([e for e in entries if os.path.isdir(os.path.join(context_base, e))])
        except OSError:
            return 0
