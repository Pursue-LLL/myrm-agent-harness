# [INPUT]: ContextHealthConfig, ContextHealthDoctorProbe, ContextSavingsMetrics, ContextUsageSnapshot, EphemeralAutoPurgeSentry, HealthDoctorDiagnosis, HealthWatermarkLevel, PurgeReceipt, RealtimeHealthGauge, ToolExpenditureItem
# [OUTPUT]: RealtimeContextHealthDashboardAndAutoPurgeSentrySuite
# [POS]: agent/context_management/context_health_dashboard/realtime_context_health_suite.py

"""Unified facade orchestrating realtime context health metering, auto-purge sentry, and doctor probe.

[INPUT]
- Domain models: ContextUsageSnapshot, ContextSavingsMetrics, HealthWatermarkLevel, ToolExpenditureItem, PurgeReceipt, HealthDoctorDiagnosis, ContextHealthConfig.
- Component engines: RealtimeHealthGauge, EphemeralAutoPurgeSentry, ContextHealthDoctorProbe.

[OUTPUT]
- RealtimeContextHealthDashboardAndAutoPurgeSentrySuite: Top-level unified facade.

[POS]
Main entry point in agent/context_management/context_health_dashboard for observability and storage hygiene.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .context_health_doctor_probe import ContextHealthDoctorProbe
from .context_health_types import (
    ContextHealthConfig,
    ContextSavingsMetrics,
    ContextUsageSnapshot,
    HealthDoctorDiagnosis,
    HealthWatermarkLevel,
    PurgeReceipt,
    ToolExpenditureItem,
)
from .ephemeral_auto_purge_sentry import EphemeralAutoPurgeSentry
from .realtime_health_gauge import RealtimeHealthGauge


class RealtimeContextHealthDashboardAndAutoPurgeSentrySuite:
    """Unified facade managing realtime context health monitoring, disk GC, and preflight environment doctor checks."""

    def __init__(
        self,
        config: ContextHealthConfig | None = None,
        gauge: RealtimeHealthGauge | None = None,
        sentry: EphemeralAutoPurgeSentry | None = None,
        doctor: ContextHealthDoctorProbe | None = None,
    ) -> None:
        self._config = config or ContextHealthConfig()
        self._gauge = gauge or RealtimeHealthGauge(self._config)
        self._sentry = sentry or EphemeralAutoPurgeSentry(self._config)
        self._doctor = doctor or ContextHealthDoctorProbe(self._config)

    @property
    def config(self) -> ContextHealthConfig:
        return self._config

    def evaluate_health(
        self,
        session_id: str,
        current_tokens: int,
        raw_offloaded_tokens: int = 0,
        tool_stats: Mapping[str, tuple[int, int]] | None = None,
        custom_window_capacity: int | None = None,
    ) -> ContextUsageSnapshot:
        """Evaluates realtime context capacity saturation, tool hotspots, and offload savings."""
        return self._gauge.evaluate_health(
            session_id=session_id,
            current_tokens=current_tokens,
            raw_offloaded_tokens=raw_offloaded_tokens,
            tool_stats=tool_stats,
            custom_window_capacity=custom_window_capacity,
        )

    def render_health_card(self, snapshot: ContextUsageSnapshot) -> str:
        """Renders compact context health card for prompt injection or UI status widgets."""
        return self._gauge.render_compact_health_card(snapshot)

    def scan_ephemeral_storage(
        self,
        session_id: str,
        base_root: str | None = None,
    ) -> tuple[int, int]:
        """Scans ephemeral files for a session and returns (file_count, total_bytes)."""
        return self._sentry.scan_ephemeral_usage(session_id=session_id, base_root=base_root)

    def purge_ephemeral_storage(
        self,
        session_id: str,
        confirm: bool = True,
        base_root: str | None = None,
    ) -> PurgeReceipt:
        """Permanently reclaims temporary session index files and FTS5 databases."""
        return self._sentry.purge_session_ephemeral_storage(
            session_id=session_id,
            confirm=confirm,
            base_root=base_root,
        )

    def diagnose_environment(
        self,
        base_root: str | None = None,
    ) -> HealthDoctorDiagnosis:
        """Executes non-destructive environment checks on SQLite FTS5 and workspace permissions."""
        return self._doctor.run_health_diagnosis(base_root=base_root)
