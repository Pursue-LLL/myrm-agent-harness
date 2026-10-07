"""Unit tests for Tiered Prompt Cache and Hour Clock Governor Suite (Item 222).

[INPUT]
- PromptCacheClockGovernorEngine, PromptCacheClockConfig, ContextClockSpec, ToolChoiceMode, CacheTierKind.
- Timestamps across minutes, hours, and various tool choice payloads.

[OUTPUT]
- Deterministic verification of hourly clock bucketing, prefix byte stability (100%),
- forced tool choice cache bypass, and three-tier layout assembly.

[POS]
- Verifies prompt cache preservation against clock jitter and tool_choice pollution.
"""

from __future__ import annotations

import datetime
import pytest

from myrm_agent_harness.agent.context_management.prompt_cache_clock import (
    CacheTierKind,
    ClockBucketResolution,
    ContextClockSpec,
    PromptCacheClockConfig,
    PromptCacheClockGovernorEngine,
    TieredAssemblyResult,
    ToolChoiceMode,
)


def test_context_clock_hourly_bucketing_and_stability() -> None:
    """Verifies that timestamps throughout an entire hour generate 100% identical byte strings."""
    engine = PromptCacheClockGovernorEngine(
        config=PromptCacheClockConfig(clock_resolution=ClockBucketResolution.HOUR_BUCKET)
    )

    # Base: 2026-10-08 05:00:00 UTC
    base_dt = datetime.datetime(2026, 10, 8, 5, 0, 0, tzinfo=datetime.timezone.utc)
    base_ts = base_dt.timestamp()

    # Minute 02, second 15
    ts_min_2 = base_ts + 135
    # Minute 45, second 30
    ts_min_45 = base_ts + 2730
    # Minute 59, second 59
    ts_min_59 = base_ts + 3599

    c_base = engine.resolve_context_clock(timestamp=base_ts)
    c_2 = engine.resolve_context_clock(timestamp=ts_min_2)
    c_45 = engine.resolve_context_clock(timestamp=ts_min_45)
    c_59 = engine.resolve_context_clock(timestamp=ts_min_59)

    # All must produce exact same string within the same hour
    assert c_base.bucketed_time_str == "2026-10-08 05:00 UTC"
    assert c_2.bucketed_time_str == "2026-10-08 05:00 UTC"
    assert c_45.bucketed_time_str == "2026-10-08 05:00 UTC"
    assert c_59.bucketed_time_str == "2026-10-08 05:00 UTC"

    # Transition to hour 06
    ts_hour_6 = base_ts + 3601
    c_6 = engine.resolve_context_clock(timestamp=ts_hour_6)
    assert c_6.bucketed_time_str == "2026-10-08 06:00 UTC"


def test_tool_choice_cache_bypass_guard() -> None:
    """Verifies that forced tool choice rounds bypass cache breakpoints to avoid key pollution."""
    engine = PromptCacheClockGovernorEngine()

    # Auto mode is eligible for cache breakpoint
    assert engine.is_rolling_breakpoint_eligible(ToolChoiceMode.AUTO) is True
    assert engine.is_rolling_breakpoint_eligible("auto", None) is True

    # Forced tool mode is NOT eligible (bypassed)
    assert engine.is_rolling_breakpoint_eligible(ToolChoiceMode.FORCED_TOOL) is False
    assert engine.is_rolling_breakpoint_eligible("forced_tool") is False
    assert (
        engine.is_rolling_breakpoint_eligible(
            ToolChoiceMode.AUTO,
            tool_choice_payload={"type": "tool", "name": "checkout_cart"},
        )
        is False
    )

    # When bypass switch is disabled, all modes remain eligible
    lenient_engine = PromptCacheClockGovernorEngine(
        config=PromptCacheClockConfig(bypass_cache_on_forced_tool=False)
    )
    assert lenient_engine.is_rolling_breakpoint_eligible(ToolChoiceMode.FORCED_TOOL) is True


def test_three_tier_layout_assembly() -> None:
    """Verifies three-tier architectural layout and conditional cache breakpoint placement."""
    engine = PromptCacheClockGovernorEngine()

    base_dt = datetime.datetime(2026, 10, 8, 5, 12, 0, tzinfo=datetime.timezone.utc)
    ts = base_dt.timestamp()

    tier1_text = "You are the Myrm Lead Autonomous Engineer."
    tier2_text = "Project rules: strict PEP8, 0 Any types, <400 lines."
    tier3_text = "Current URL: https://internal.dev/console/view"

    # Round 1: Auto tool mode
    res_auto = engine.assemble_three_tier_request(
        tier1_static_system=tier1_text,
        tier2_session_context=tier2_text,
        tier3_transient_instructions=tier3_text,
        tool_choice_mode=ToolChoiceMode.AUTO,
        timestamp=ts,
    )

    assert res_auto.rolling_breakpoint_eligible is True
    assert res_auto.cache_breakpoints_count == 2  # Tier 1 + Tier 2
    assert len(res_auto.system_blocks) == 3
    assert res_auto.system_blocks[0]["tier"] == CacheTierKind.TIER_1_STATIC_GLOBAL.value
    assert res_auto.system_blocks[1]["tier"] == CacheTierKind.TIER_2_SESSION_CONTEXT.value
    assert res_auto.system_blocks[2]["tier"] == CacheTierKind.TIER_3_TRANSIENT_TURN.value
    assert "[Session Clock]: 2026-10-08 05:00 UTC" in str(res_auto.system_blocks[1]["text"])

    # Round 2: Forced tool mode (Tier 2 breakpoint bypassed)
    res_forced = engine.assemble_three_tier_request(
        tier1_static_system=tier1_text,
        tier2_session_context=tier2_text,
        tier3_transient_instructions=tier3_text,
        tool_choice_mode=ToolChoiceMode.FORCED_TOOL,
        timestamp=ts,
    )

    assert res_forced.rolling_breakpoint_eligible is False
    assert res_forced.cache_breakpoints_count == 1  # Only Tier 1 retains breakpoint


def test_prefix_stability_metric() -> None:
    """Verifies 100% byte prefix stability across multiple turns within the same clock hour."""
    engine = PromptCacheClockGovernorEngine()

    base_dt = datetime.datetime(2026, 10, 8, 5, 10, 0, tzinfo=datetime.timezone.utc)
    ts1 = base_dt.timestamp()
    ts2 = ts1 + 1800  # 30 minutes later, still hour 05

    tier1 = "Global static system prompt and standard tool schemas."
    tier2 = "User preference: Chinese language, high performance."

    # Turn 1
    res1 = engine.assemble_three_tier_request(
        tier1_static_system=tier1,
        tier2_session_context=tier2,
        tier3_transient_instructions="Turn 1 instruction",
        timestamp=ts1,
    )

    # Turn 2 (30 minutes later, different transient instruction)
    res2 = engine.assemble_three_tier_request(
        tier1_static_system=tier1,
        tier2_session_context=tier2,
        tier3_transient_instructions="Turn 2 completely different query",
        timestamp=ts2,
    )

    stability = engine.evaluate_cache_prefix_stability(
        res1.system_blocks,
        res2.system_blocks,
    )
    # The cached prefix (Tier 1 + Tier 2) is 100% byte-for-byte identical!
    assert stability == 1.0
