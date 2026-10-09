"""Comprehensive unit tests for CompactBeforeSendTokenChipSuite.

[INPUT]
- compact_chip types, calculator, renderer, and facade suite.

[OUTPUT]
- Deterministic verification of token estimations, staleness & pressure triggers,
  user preference overrides, chip display rendering, and facade exports.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_compact_before_send_token_chip_suite.py
"""

import pytest

from myrm_agent_harness.agent import (
    CompactBeforeSendTokenChipSuite as RootExportedSuite,
)
from myrm_agent_harness.agent.context_management import (
    CompactActionPreference,
    CompactBeforeSendConfig,
    CompactBeforeSendTokenChipSuite,
    CompactChipVerdict,
    CompactPreflightCalculator,
    CompactPreflightEstimate,
    SendActionLabelRenderer,
    SendButtonDisplaySpec,
)


def test_preflight_calculator_staleness_and_pressure() -> None:
    """Verifies that context estimate triggers on staleness and pressure thresholds."""
    config = CompactBeforeSendConfig(
        stale_threshold_seconds=3600.0,
        pressure_threshold_ratio=0.75,
        min_display_tokens=500,
    )
    calculator = CompactPreflightCalculator(config)

    # 1. Normal state: neither stale nor pressured
    est_normal = calculator.calculate_estimate(
        total_tokens=10_000,
        max_context_tokens=100_000,
        idle_seconds=600.0,  # 10m < 1h
    )
    assert est_normal.is_stale is False
    assert est_normal.is_pressured is False
    assert est_normal.estimated_compressible_tokens == 0
    assert calculator.resolve_will_compact(est_normal, CompactActionPreference.AUTO_COMPACT) is False

    # 2. Stale state: idle > 1 hour
    est_stale = calculator.calculate_estimate(
        total_tokens=10_000,
        max_context_tokens=100_000,
        idle_seconds=4000.0,  # > 3600s
    )
    assert est_stale.is_stale is True
    assert est_stale.is_pressured is False
    assert est_stale.estimated_compressible_tokens == 6500
    assert calculator.resolve_will_compact(est_stale, CompactActionPreference.AUTO_COMPACT) is True

    # 3. Pressured state: tokens > 75% max_context_tokens
    est_pressured = calculator.calculate_estimate(
        total_tokens=80_000,
        max_context_tokens=100_000,
        idle_seconds=300.0,  # Fresh session, but high pressure
    )
    assert est_pressured.is_stale is False
    assert est_pressured.is_pressured is True
    assert est_pressured.estimated_compressible_tokens == 52_000
    assert calculator.resolve_will_compact(est_pressured, CompactActionPreference.AUTO_COMPACT) is True


def test_user_preference_overrides() -> None:
    """Verifies user preference overrides (keep full history vs force compact)."""
    calculator = CompactPreflightCalculator(CompactBeforeSendConfig())

    # High pressure estimate that defaults to compaction
    est = calculator.calculate_estimate(
        total_tokens=80_000,
        max_context_tokens=100_000,
        idle_seconds=100.0,
    )
    assert calculator.resolve_will_compact(est, CompactActionPreference.AUTO_COMPACT) is True

    # User explicitly clicks chip to keep full history
    assert calculator.resolve_will_compact(est, CompactActionPreference.FORCE_KEEP_FULL) is False

    # Small fresh context that defaults to no compact
    est_small = calculator.calculate_estimate(
        total_tokens=2000,
        max_context_tokens=100_000,
        idle_seconds=10.0,
    )
    assert calculator.resolve_will_compact(est_small, CompactActionPreference.AUTO_COMPACT) is False

    # User manually requests compact
    assert calculator.resolve_will_compact(est_small, CompactActionPreference.FORCE_COMPACT) is True


def test_label_renderer_formatting_and_verdicts() -> None:
    """Verifies honest button label, tooltip, and chip copy rendering."""
    renderer = SendActionLabelRenderer()

    assert renderer.format_tokens(500) == "500"
    assert renderer.format_tokens(42_000) == "42k"
    assert renderer.format_tokens(1_500_000) == "1.5M"

    calc = CompactPreflightCalculator(CompactBeforeSendConfig())

    # Case A: Compaction will trigger
    est_pressured = calc.calculate_estimate(80_000, 100_000, 10.0)
    spec_trigger = renderer.render_display_spec(
        estimate=est_pressured,
        preference=CompactActionPreference.AUTO_COMPACT,
        will_compact=True,
    )
    assert spec_trigger.verdict == CompactChipVerdict.COMPACT_WILL_TRIGGER
    assert spec_trigger.will_compact is True
    assert spec_trigger.primary_send_label == "Compact and send"
    assert "Compact ~52k tokens" in spec_trigger.chip_text
    assert spec_trigger.chip_visible is True
    assert "Next send compacts ~52k tokens" in spec_trigger.tooltip

    # Case B: User overrides to keep full history
    spec_keep_full = renderer.render_display_spec(
        estimate=est_pressured,
        preference=CompactActionPreference.FORCE_KEEP_FULL,
        will_compact=False,
    )
    assert spec_keep_full.verdict == CompactChipVerdict.KEEP_FULL_OVERRIDDEN
    assert spec_keep_full.will_compact is False
    assert spec_keep_full.primary_send_label == "Send"
    assert spec_keep_full.chip_text == "Full history kept"
    assert spec_keep_full.chip_visible is True
    assert "without preflight compaction" in spec_keep_full.tooltip

    # Case C: Normal unpressured context
    est_normal = calc.calculate_estimate(5000, 100_000, 10.0)
    spec_normal = renderer.render_display_spec(
        estimate=est_normal,
        preference=CompactActionPreference.AUTO_COMPACT,
        will_compact=False,
    )
    assert spec_normal.verdict == CompactChipVerdict.HIDDEN
    assert spec_normal.will_compact is False
    assert spec_normal.primary_send_label == "Send"
    assert spec_normal.chip_visible is False


def test_facade_suite_operations_and_root_exports() -> None:
    """Verifies unified facade suite entrypoints and root package lazy resolution."""
    suite = CompactBeforeSendTokenChipSuite()

    # Preflight estimation check
    est = suite.estimate_context(total_tokens=90_000, max_context_tokens=100_000, idle_seconds=0.0)
    assert est.is_pressured is True

    # Resolving full spec
    spec = suite.resolve_send_spec(
        total_tokens=90_000,
        max_context_tokens=100_000,
        idle_seconds=0.0,
        preference=CompactActionPreference.AUTO_COMPACT,
    )
    assert spec.will_compact is True
    assert spec.primary_send_label == "Compact and send"

    # Decision helper
    assert suite.will_compact(90_000, 100_000, 0.0) is True
    assert (
        suite.will_compact(90_000, 100_000, 0.0, preference=CompactActionPreference.FORCE_KEEP_FULL)
        is False
    )

    # Root lazy export integrity
    assert RootExportedSuite is CompactBeforeSendTokenChipSuite
    inst = RootExportedSuite()
    assert isinstance(inst, CompactBeforeSendTokenChipSuite)
    assert inst.calculator is not None
    assert inst.renderer is not None
