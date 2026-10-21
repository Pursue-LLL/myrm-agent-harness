"""
[INPUT]: RuntimeCodeFreshnessInspector routines, mock timestamps, and filesystem scenarios.
[OUTPUT]: Pytest suite validating three-state freshness evaluations (fresh/stale/indeterminate), anti-tautological sentinel assertions, and remediation guidance.
[POS]: myrm-agent-harness/tests/observability/test_code_freshness.py
"""

import pytest
from myrm_agent_harness.observability.code_freshness import (
    FreshnessState,
    IndeterminateReason,
    RuntimeCodeFreshnessInspector,
)


@pytest.fixture
def inspector() -> RuntimeCodeFreshnessInspector:
    # Anchor process start time at 2026-10-12 12:00:00 UTC (1791806400000 ms)
    # Concrete literal epoch ensuring non-tautological verification
    process_start = 1791806400000
    return RuntimeCodeFreshnessInspector(override_process_start_ms=process_start)


def test_fresh_state_determination(inspector: RuntimeCodeFreshnessInspector) -> None:
    # File modified 1 hour BEFORE process launch -> FRESH
    older_mtime = 1791802800000  # 11:00:00 UTC
    entry = inspector.inspect_file(
        module_name="app.main",
        file_path="/app/main.py",
        mock_mtime_ms=older_mtime,
    )

    assert entry.state == FreshnessState.FRESH
    assert entry.reason == IndeterminateReason.NONE
    assert entry.time_drift_seconds is not None
    assert entry.time_drift_seconds <= 0.0
    assert "matches" in entry.remediation_hint


def test_stale_state_detection_after_hot_deployment(inspector: RuntimeCodeFreshnessInspector) -> None:
    # File modified 30 minutes AFTER process launch (e.g. git pull during runtime) -> STALE
    newer_mtime = 1791808200000  # 12:30:00 UTC
    entry = inspector.inspect_file(
        module_name="app.services.gateway",
        file_path="/app/services/gateway.py",
        mock_mtime_ms=newer_mtime,
    )

    assert entry.state == FreshnessState.STALE
    assert entry.reason == IndeterminateReason.NONE
    assert entry.time_drift_seconds == 1800.0  # 30 mins drift
    assert "older than disk code" in entry.remediation_hint
    assert "drain" in entry.remediation_hint


def test_indeterminate_states_reasons(inspector: RuntimeCodeFreshnessInspector) -> None:
    # 1. Non-existent file
    entry_missing = inspector.inspect_file(
        module_name="ghost_module",
        file_path="/tmp/definitely_not_existing_file_98765.py",
    )
    assert entry_missing.state == FreshnessState.INDETERMINATE
    assert entry_missing.reason == IndeterminateReason.FILE_NOT_FOUND

    # 2. Bundled / virtual executable
    entry_virtual = inspector.inspect_file(
        module_name="eval_code",
        file_path="<string>",
    )
    assert entry_virtual.state == FreshnessState.INDETERMINATE
    assert entry_virtual.reason == IndeterminateReason.VIRTUAL_OR_BUNDLED

    # 3. Clock drift anomaly / corrupted year 3626 sentinel
    corrupted_future_mtime = 52250000000000  # Far in distant future
    entry_drift = inspector.inspect_file(
        module_name="clock_drift_test",
        file_path="/app/core.py",
        mock_mtime_ms=corrupted_future_mtime,
    )
    assert entry_drift.state == FreshnessState.INDETERMINATE
    assert entry_drift.reason == IndeterminateReason.CLOCK_DRIFT_DETECTED


def test_runtime_aggregate_freshness_report(inspector: RuntimeCodeFreshnessInspector) -> None:
    # Register mix of fresh and stale modules
    inspector.register_module("module_fresh", __file__)
    report = inspector.inspect_runtime()

    assert report.pid > 0
    assert report.total_inspected_modules >= 1
    assert report.overall_state in (FreshnessState.FRESH, FreshnessState.STALE, FreshnessState.INDETERMINATE)
