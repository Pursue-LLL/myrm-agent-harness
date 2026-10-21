"""
[INPUT]: Process launch metadata, filesystem timestamps, and source file descriptors.
[OUTPUT]: High-performance inspector evaluating three-state runtime code freshness and anti-tautological verifications.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/code_freshness/inspector.py
"""

import os
import sys
import time
from typing import Dict, List, Optional
from myrm_agent_harness.observability.code_freshness.models import (
    FreshnessState,
    IndeterminateReason,
    ModuleFreshnessEntry,
    RuntimeFreshnessReport,
)

# Year 2038 / reasonable sentinel bounds (between 2020-01-01 and 2035-01-01)
_MIN_VALID_EPOCH_MS = 1577836800000  # 2020-01-01 UTC
_MAX_VALID_EPOCH_MS = 2051222400000  # 2035-01-01 UTC


class RuntimeCodeFreshnessInspector:
    """Evaluates whether current executing process is running stale code compared to on-disk files."""

    def __init__(self, override_process_start_ms: Optional[int] = None) -> None:
        self._process_start_ms = override_process_start_ms or int(time.time() * 1000)
        self._registered_modules: Dict[str, str] = {}

    def set_process_start_time(self, timestamp_ms: int) -> None:
        """Allow explicit test injection of process launch time."""
        self._process_start_ms = timestamp_ms

    def register_module(self, module_name: str, file_path: str) -> None:
        """Register a key script or package entrypoint for periodic freshness monitoring."""
        self._registered_modules[module_name] = file_path

    def inspect_file(
        self,
        module_name: str,
        file_path: str,
        mock_mtime_ms: Optional[int] = None,
        force_unreadable: bool = False,
    ) -> ModuleFreshnessEntry:
        """Examine on-disk modification time against current in-memory process start time."""
        # 1. Virtual / bundled check
        if getattr(sys, "frozen", False) or file_path.startswith("<"):
            return ModuleFreshnessEntry(
                module_name=module_name,
                file_path=file_path,
                process_start_time_ms=self._process_start_ms,
                disk_mtime_ms=None,
                time_drift_seconds=None,
                state=FreshnessState.INDETERMINATE,
                reason=IndeterminateReason.VIRTUAL_OR_BUNDLED,
                remediation_hint="Executable runs from bundled image; modification time is non-applicable.",
            )

        # 2. Permission / unreadable simulation
        if force_unreadable:
            return ModuleFreshnessEntry(
                module_name=module_name,
                file_path=file_path,
                process_start_time_ms=self._process_start_ms,
                disk_mtime_ms=None,
                time_drift_seconds=None,
                state=FreshnessState.INDETERMINATE,
                reason=IndeterminateReason.PERMISSION_DENIED,
                remediation_hint="Check read permissions on source file.",
            )

        # 3. File existence check
        if mock_mtime_ms is None and not os.path.exists(file_path):
            return ModuleFreshnessEntry(
                module_name=module_name,
                file_path=file_path,
                process_start_time_ms=self._process_start_ms,
                disk_mtime_ms=None,
                time_drift_seconds=None,
                state=FreshnessState.INDETERMINATE,
                reason=IndeterminateReason.FILE_NOT_FOUND,
                remediation_hint="File path not found on disk; verify repository installation.",
            )

        # 4. Read modification timestamp
        try:
            mtime_ms = mock_mtime_ms if mock_mtime_ms is not None else int(os.path.getmtime(file_path) * 1000)
        except OSError:
            return ModuleFreshnessEntry(
                module_name=module_name,
                file_path=file_path,
                process_start_time_ms=self._process_start_ms,
                disk_mtime_ms=None,
                time_drift_seconds=None,
                state=FreshnessState.INDETERMINATE,
                reason=IndeterminateReason.PERMISSION_DENIED,
                remediation_hint="Error querying file filesystem metadata.",
            )

        # 5. Sanity check for clock drift / anomalous future dates (anti-tautological guard)
        if mtime_ms < _MIN_VALID_EPOCH_MS or mtime_ms > _MAX_VALID_EPOCH_MS:
            return ModuleFreshnessEntry(
                module_name=module_name,
                file_path=file_path,
                process_start_time_ms=self._process_start_ms,
                disk_mtime_ms=mtime_ms,
                time_drift_seconds=None,
                state=FreshnessState.INDETERMINATE,
                reason=IndeterminateReason.CLOCK_DRIFT_DETECTED,
                remediation_hint="Filesystem timestamp outside plausible decade bounds; sync NTP clock.",
            )

        # 6. Evaluate freshness: process_start_ms vs disk_mtime_ms
        drift_seconds = round((mtime_ms - self._process_start_ms) / 1000.0, 2)
        if mtime_ms > self._process_start_ms:
            # Disk is newer than running process -> STALE
            return ModuleFreshnessEntry(
                module_name=module_name,
                file_path=file_path,
                process_start_time_ms=self._process_start_ms,
                disk_mtime_ms=mtime_ms,
                time_drift_seconds=drift_seconds,
                state=FreshnessState.STALE,
                reason=IndeterminateReason.NONE,
                remediation_hint=(
                    f"Process is {drift_seconds}s older than disk code. "
                    "Gracefully drain active sessions and reload process."
                ),
            )
        else:
            # Process was launched after or concurrent with disk file -> FRESH
            return ModuleFreshnessEntry(
                module_name=module_name,
                file_path=file_path,
                process_start_time_ms=self._process_start_ms,
                disk_mtime_ms=mtime_ms,
                time_drift_seconds=drift_seconds,
                state=FreshnessState.FRESH,
                reason=IndeterminateReason.NONE,
                remediation_hint="Runtime in-memory bytecode matches current disk version.",
            )

    def inspect_runtime(self, extra_modules: Optional[Dict[str, str]] = None) -> RuntimeFreshnessReport:
        """Generate comprehensive code freshness evaluation across all registered files."""
        all_targets: Dict[str, str] = dict(self._registered_modules)
        if extra_modules:
            all_targets.update(extra_modules)

        # Default self module if empty
        if not all_targets:
            all_targets["code_freshness.inspector"] = os.path.abspath(__file__)

        entries: List[ModuleFreshnessEntry] = []
        for name, path in all_targets.items():
            entries.append(self.inspect_file(name, path))

        stale_count = sum(1 for e in entries if e.state == FreshnessState.STALE)
        fresh_count = sum(1 for e in entries if e.state == FreshnessState.FRESH)
        indet_count = sum(1 for e in entries if e.state == FreshnessState.INDETERMINATE)

        if stale_count > 0:
            overall = FreshnessState.STALE
        elif fresh_count > 0:
            overall = FreshnessState.FRESH
        else:
            overall = FreshnessState.INDETERMINATE

        return RuntimeFreshnessReport(
            pid=os.getpid(),
            overall_state=overall,
            total_inspected_modules=len(entries),
            stale_modules_count=stale_count,
            fresh_modules_count=fresh_count,
            indeterminate_count=indet_count,
            inspected_at_ms=int(time.time() * 1000),
            details=entries,
        )
