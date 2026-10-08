# [INPUT]: ContextHealthConfig, ContextHealthDoctorProbe, ContextSavingsMetrics, ContextUsageSnapshot, EphemeralAutoPurgeSentry, HealthDoctorDiagnosis, HealthWatermarkLevel, PurgeReceipt, RealtimeContextHealthDashboardAndAutoPurgeSentrySuite, RealtimeHealthGauge, ToolExpenditureItem
# [OUTPUT]: test_realtime_context_health_suite.py
# [POS]: tests/agent/context_management/test_realtime_context_health_suite.py

"""Comprehensive unit tests for RealtimeContextHealthDashboardAndAutoPurgeSentrySuite.

Verifies:
1. Mathematical capacity watermarks (HEALTHY, WARNING, CRITICAL, OVERFLOW) and headroom calculations.
2. Context savings ratio (e.g. >90%) and multiplier metrics based on sandbox/indexing offloads.
3. Tool consumption hotspot aggregations and share percentages.
4. Compact <context_health> dashboard card formatting for UI widgets and prompt injection.
5. Ephemeral auto-purge sentry directory scanning, safety fences, and physical disk reclamation.
6. Context health doctor probe diagnosing SQLite FTS5 capabilities and write permissions.
7. Unified end-to-end facade orchestration.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from myrm_agent_harness.agent.context_management.context_health_dashboard import (
    ContextHealthConfig,
    ContextHealthDoctorProbe,
    ContextSavingsMetrics,
    ContextUsageSnapshot,
    EphemeralAutoPurgeSentry,
    HealthDoctorDiagnosis,
    HealthWatermarkLevel,
    PurgeReceipt,
    RealtimeContextHealthDashboardAndAutoPurgeSentrySuite,
    RealtimeHealthGauge,
    ToolExpenditureItem,
)


def test_realtime_health_gauge_watermark_and_headroom() -> None:
    """Verifies watermark classification across different usage thresholds."""
    gauge = RealtimeHealthGauge(ContextHealthConfig(default_window_capacity=100_000))

    # 1. Healthy state (<75%)
    snap_healthy = gauge.evaluate_health(session_id="s1", current_tokens=50_000)
    assert snap_healthy.watermark_level == HealthWatermarkLevel.HEALTHY
    assert snap_healthy.usage_percentage == 50.0
    assert snap_healthy.safe_headroom_tokens == 50_000

    # 2. Warning state (75% - 90%)
    snap_warning = gauge.evaluate_health(session_id="s1", current_tokens=80_000)
    assert snap_warning.watermark_level == HealthWatermarkLevel.WARNING
    assert snap_warning.safe_headroom_tokens == 20_000

    # 3. Critical state (90% - 100%)
    snap_critical = gauge.evaluate_health(session_id="s1", current_tokens=95_000)
    assert snap_critical.watermark_level == HealthWatermarkLevel.CRITICAL
    assert snap_critical.safe_headroom_tokens == 5_000

    # 4. Overflow state (>=100%)
    snap_overflow = gauge.evaluate_health(session_id="s1", current_tokens=105_000)
    assert snap_overflow.watermark_level == HealthWatermarkLevel.OVERFLOW
    assert snap_overflow.safe_headroom_tokens == 0


def test_realtime_health_gauge_savings_ratio_and_multiplier() -> None:
    """Verifies mathematical savings percentage and multiplier from offloaded tokens."""
    gauge = RealtimeHealthGauge()

    # 10,000 resident tokens, 90,000 offloaded tokens -> 100,000 raw total
    snapshot = gauge.evaluate_health(
        session_id="s_savings",
        current_tokens=10_000,
        raw_offloaded_tokens=90_000,
    )

    savings = snapshot.savings
    assert savings.raw_unbounded_tokens == 100_000
    assert savings.context_resident_tokens == 10_000
    assert savings.tokens_saved == 90_000
    assert savings.savings_ratio_pct == 90.0
    assert savings.savings_multiplier_x == 10.0


def test_realtime_health_gauge_tool_hotspot_breakdown() -> None:
    """Verifies tool call volume aggregation, token estimation, and share calculation."""
    gauge = RealtimeHealthGauge(ContextHealthConfig(top_tools_limit=3))

    tool_stats = {
        "web_search": (5, 40_000),      # ~10,000 tokens
        "read_file": (20, 20_000),      # ~5,000 tokens
        "bash": (2, 4_000),             # ~1,000 tokens
        "calculator": (10, 400),        # ~100 tokens
    }

    snapshot = gauge.evaluate_health(
        session_id="s_tools",
        current_tokens=25_000,
        tool_stats=tool_stats,
    )

    top_tools = snapshot.top_tools
    assert len(top_tools) == 3
    assert top_tools[0].tool_name == "web_search"
    assert top_tools[0].token_estimate == 10_000
    assert top_tools[1].tool_name == "read_file"
    assert top_tools[2].tool_name == "bash"
    assert sum(t.share_percentage for t in top_tools) > 95.0


def test_compact_health_card_rendering() -> None:
    """Verifies compact text formatting and alert banners in warning states."""
    gauge = RealtimeHealthGauge(ContextHealthConfig(default_window_capacity=100_000))

    snapshot = gauge.evaluate_health(
        session_id="s_card",
        current_tokens=85_000,
        raw_offloaded_tokens=150_000,
        tool_stats={"browser": (3, 20_000)},
    )

    card = gauge.render_compact_health_card(snapshot)
    assert "<context_health>" in card
    assert "</context_health>" in card
    assert "85.0% - WARNING" in card
    assert "Headroom: 15,000 tokens" in card
    assert "Savings:" in card
    assert "Top Tool Hotspots:" in card
    assert "CAPACITY ALERT" in card


def test_ephemeral_auto_purge_sentry_safety_and_cleanup() -> None:
    """Verifies safety fences, file discovery, and physical file deletion."""
    with tempfile.TemporaryDirectory() as temp_root:
        sentry = EphemeralAutoPurgeSentry(
            ContextHealthConfig(base_ephemeral_dir_template=".context/{session_id}")
        )
        session_id = "test_purge_session_123"

        # Create simulated session temporary directory
        session_dir = sentry.resolve_session_ephemeral_dir(session_id, base_root=temp_root)
        os.makedirs(session_dir, exist_ok=True)

        # Write test dummy files
        f1 = os.path.join(session_dir, "kb.sqlite")
        f2 = os.path.join(session_dir, "evicted_output.txt")
        with open(f1, "w") as f:
            f.write("A" * 1024)
        with open(f2, "w") as f:
            f.write("B" * 2048)

        # 1. Usage scan
        file_count, byte_size = sentry.scan_ephemeral_usage(session_id, base_root=temp_root)
        assert file_count == 2
        assert byte_size == 3072

        # 2. Skip when not confirmed
        unconfirmed_receipt = sentry.purge_session_ephemeral_storage(
            session_id=session_id,
            confirm=False,
            base_root=temp_root,
        )
        assert unconfirmed_receipt.status == "skipped_not_confirmed"
        assert os.path.exists(session_dir)

        # 3. Successful purge
        receipt = sentry.purge_session_ephemeral_storage(
            session_id=session_id,
            confirm=True,
            base_root=temp_root,
        )
        assert receipt.status == "success"
        assert receipt.purged_files_count == 2
        assert receipt.reclaimed_bytes == 3072
        assert not os.path.exists(session_dir)

        # 4. Safety fence test: path without session_id must raise ValueError
        with pytest.raises(ValueError, match="Target path does not contain session_id"):
            sentry._assert_safe_directory("/tmp/arbitrary_folder", "different_session")


def test_context_health_doctor_probe_diagnostics() -> None:
    """Verifies non-destructive SQLite FTS5 detection and directory diagnosis."""
    probe = ContextHealthDoctorProbe()
    diagnosis = probe.run_health_diagnosis()

    assert diagnosis.fts5_supported is True
    assert diagnosis.trigram_supported is True
    assert diagnosis.storage_writable is True
    assert diagnosis.available_disk_mb > 0
    assert diagnosis.is_healthy is True


def test_facade_end_to_end_orchestration() -> None:
    """Verifies end-to-end suite combining health gauge, purge sentry, and doctor probe."""
    with tempfile.TemporaryDirectory() as temp_root:
        suite = RealtimeContextHealthDashboardAndAutoPurgeSentrySuite()

        # 1. Health evaluation
        snap = suite.evaluate_health(
            session_id="sess_facade",
            current_tokens=40_000,
            raw_offloaded_tokens=60_000,
            tool_stats={"grep": (10, 8_000)},
        )
        assert snap.watermark_level == HealthWatermarkLevel.HEALTHY
        card = suite.render_health_card(snap)
        assert "<context_health>" in card

        # 2. Ephemeral scan & purge
        ephemeral_dir = suite._sentry.resolve_session_ephemeral_dir("sess_facade", base_root=temp_root)
        os.makedirs(ephemeral_dir, exist_ok=True)
        with open(os.path.join(ephemeral_dir, "temp.log"), "w") as f:
            f.write("hello")

        count, bytes_used = suite.scan_ephemeral_storage("sess_facade", base_root=temp_root)
        assert count == 1
        assert bytes_used == 5

        receipt = suite.purge_ephemeral_storage("sess_facade", confirm=True, base_root=temp_root)
        assert receipt.status == "success"
        assert receipt.purged_files_count == 1

        # 3. Doctor diagnosis
        diag = suite.diagnose_environment(base_root=temp_root)
        assert diag.is_healthy is True
