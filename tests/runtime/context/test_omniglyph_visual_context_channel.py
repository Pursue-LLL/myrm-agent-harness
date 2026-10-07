"""Unit tests for OmniGlyph multimodal visual context channel and Ultra token governor.

Verifies fail-closed risk isolation, explicit opt-in enforcement, break-even
cost arbitration, heuristic pruning, and end-to-end rasterization to visual glyphs.
"""

from __future__ import annotations

import base64

import pytest

from myrm_agent_harness.runtime.context.omniglyph_types import (
    BypassReason,
    OmniGlyphConfig,
    TaskRiskLevel,
)
from myrm_agent_harness.runtime.context.omniglyph_visual_channel import (
    OmniGlyphGovernor,
    OmniGlyphVisualRenderer,
)
from myrm_agent_harness.runtime.context.ultra_heuristic_filter import (
    UltraHeuristicPreFilter,
)


@pytest.fixture
def sample_long_doc() -> str:
    """Generates a realistic multi-paragraph long technical document (~18,000 chars)."""
    paragraphs = [
        (
            f"Section {i:03d} - System Architecture and Subsystem Dynamics: "
            f"Modern agent execution pipeline {i} relies on modular decoupled components "
            f"to enforce strict state persistence, reproducible execution logs, and "
            f"deterministic telemetry. Distributed worker group {i} coordinates "
            f"multi-stage evaluation across isolated sandbox boundaries, ensuring sub-50ms "
            f"TTFT and verifiable token accounting without degrading semantic fidelity."
        )
        for i in range(1, 55)
    ]
    return "\n\n".join(paragraphs)


def test_high_risk_tasks_hard_blocked_even_with_opt_in(sample_long_doc: str) -> None:
    """High and Critical risk tasks (code, secrets, finance) must be blocked fail-closed."""
    governor = OmniGlyphGovernor()
    opt_in_cfg = OmniGlyphConfig(opt_in=True)

    for risk in (TaskRiskLevel.HIGH, TaskRiskLevel.CRITICAL):
        result = governor.route_context(
            text=sample_long_doc,
            risk_level=risk,
            custom_config=opt_in_cfg,
        )

        assert not result.is_routed_to_visual
        assert result.bypassed_reason == BypassReason.HIGH_RISK_TASK
        assert len(result.rendered_glyphs) == 0
        assert result.retained_text == sample_long_doc
        assert result.net_saved_tokens == 0


def test_opt_in_strictly_required(sample_long_doc: str) -> None:
    """Without explicit opt_in=True, governor must bypass visual channel."""
    governor = OmniGlyphGovernor()
    default_cfg = OmniGlyphConfig(opt_in=False)

    result = governor.route_context(
        text=sample_long_doc,
        risk_level=TaskRiskLevel.LOW,
        custom_config=default_cfg,
    )

    assert not result.is_routed_to_visual
    assert result.bypassed_reason == BypassReason.NOT_OPTED_IN
    assert len(result.rendered_glyphs) == 0


def test_short_text_bypassed_due_to_break_even(sample_long_doc: str) -> None:
    """Short text (< break_even threshold) must not be rasterized to avoid wasting tokens."""
    governor = OmniGlyphGovernor()
    short_text = "This is a brief summary note with only a few words."
    opt_in_cfg = OmniGlyphConfig(
        opt_in=True,
        break_even_token_threshold=2500,
    )

    result = governor.route_context(
        text=short_text,
        risk_level=TaskRiskLevel.LOW,
        custom_config=opt_in_cfg,
    )

    assert not result.is_routed_to_visual
    assert result.bypassed_reason == BypassReason.TEXT_BELOW_BREAK_EVEN
    assert len(result.rendered_glyphs) == 0


def test_ultra_heuristic_filter_strips_boilerplate_and_duplicates() -> None:
    """Ultra heuristic filter removes disclaimers, duplicate paragraphs, and noisy text."""
    pre_filter = UltraHeuristicPreFilter(min_combined_threshold=0.35)
    dirty_text = (
        "Valid Analysis: Core database latency dropped by 45% after partition re-indexing.\n\n"
        "Disclaimer: The information contained in this communication is confidential.\n\n"
        "Valid Analysis: Core database latency dropped by 45% after partition re-indexing.\n\n"
        "All rights reserved. Terms of service and privacy policy apply.\n\n"
        "Deployment Log: All 12 worker nodes successfully connected to master cluster."
    )

    cleaned_text, scores = pre_filter.filter_text(
        text=dirty_text,
        target_keywords=["database", "worker"],
    )

    assert len(scores) == 5
    assert scores[0].keep_decision is True
    # Duplicate paragraph
    assert scores[2].keep_decision is False
    assert scores[2].reason == "duplicate_verbatim_paragraph"
    # Boilerplate disclaimer
    assert scores[1].keep_decision is False
    assert scores[1].reason == "detected_boilerplate_or_disclaimer"
    # Boilerplate terms
    assert scores[3].keep_decision is False
    assert scores[3].reason == "detected_boilerplate_or_disclaimer"

    assert "Valid Analysis" in cleaned_text
    assert "Deployment Log" in cleaned_text
    assert "Disclaimer:" not in cleaned_text
    assert "All rights reserved" not in cleaned_text


def test_end_to_end_omniglyph_visual_rendering(sample_long_doc: str) -> None:
    """Verifies complete visual compilation, base64 payload, and net token savings."""
    renderer = OmniGlyphVisualRenderer()
    governor = OmniGlyphGovernor(renderer=renderer)

    opt_in_cfg = OmniGlyphConfig(
        opt_in=True,
        break_even_token_threshold=1500,
        fixed_vlm_token_cost=1600,
    )

    result = governor.route_context(
        text=sample_long_doc,
        risk_level=TaskRiskLevel.LOW,
        target_keywords=["architecture", "compression", "latency"],
        custom_config=opt_in_cfg,
    )

    assert result.is_routed_to_visual is True
    assert result.bypassed_reason is None
    assert len(result.rendered_glyphs) > 0
    assert result.raw_tokens_before > 2000

    # Inspect first rendered glyph
    glyph = result.rendered_glyphs[0]
    assert glyph.mime_type == "image/png"
    assert len(glyph.checksum_sha256) == 64
    assert glyph.estimated_visual_tokens == 1600

    # Ensure image_base64 is decodable
    decoded_bytes = base64.b64decode(glyph.image_base64)
    assert len(decoded_bytes) > 0
    assert decoded_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_governor_disabled_by_config(sample_long_doc: str) -> None:
    """When disabled flag is set, governor immediately bypasses."""
    governor = OmniGlyphGovernor()
    disabled_cfg = OmniGlyphConfig(enabled=False, opt_in=True)

    result = governor.route_context(
        text=sample_long_doc,
        risk_level=TaskRiskLevel.LOW,
        custom_config=disabled_cfg,
    )

    assert not result.is_routed_to_visual
    assert result.bypassed_reason == BypassReason.DISABLED_BY_CONFIG
