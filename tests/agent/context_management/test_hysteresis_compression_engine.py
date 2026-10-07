"""Tests for Hysteresis Compression Gap and Cooldown Ladder Suite (Item 230)."""

import pytest

from myrm_agent_harness.agent.context_management.hysteresis_compression import (
    CooldownStatus,
    HysteresisCompressionEngine,
    HysteresisConfig,
    HysteresisEvaluation,
    HysteresisExecutionReport,
    SanctuaryBlock,
    SanctuaryCategory,
    WatermarkTier,
)


def test_hysteresis_dual_watermark_boundaries() -> None:
    """Verify dual-watermark hysteresis avoids thrashing by requiring 85% high trigger and 50% target."""
    config = HysteresisConfig(
        max_context_tokens=100000,
        high_watermark_ratio=0.85,
        low_watermark_ratio=0.50,
        emergency_watermark_ratio=0.95,
        base_cooldown_turns=5,
    )
    engine = HysteresisCompressionEngine(config)

    # 1. Under low watermark (< 50%): NORMAL tier
    eval_40k = engine.evaluate(current_tokens=40000, current_turn=0)
    assert eval_40k.tier == WatermarkTier.NORMAL
    assert not eval_40k.should_compress
    assert eval_40k.target_reclaim_tokens == 0
    assert not eval_40k.is_emergency

    # 2. Inside hysteresis gap (50% ~ 85%): IN_GAP tier
    eval_75k = engine.evaluate(current_tokens=75000, current_turn=0)
    assert eval_75k.tier == WatermarkTier.IN_GAP
    assert not eval_75k.should_compress
    assert eval_75k.target_reclaim_tokens == 0
    assert not eval_75k.is_emergency

    # 3. High watermark reached (85%): HIGH_WATERMARK tier
    # Deep single-pass target: down to 50% (50000 tokens), needing 36000 reclaim for 86k
    eval_86k = engine.evaluate(current_tokens=86000, current_turn=0)
    assert eval_86k.tier == WatermarkTier.HIGH_WATERMARK
    assert eval_86k.should_compress
    assert eval_86k.target_reclaim_tokens == 36000  # 86000 - 50000
    assert not eval_86k.is_emergency
    assert not eval_86k.cooldown_suppressed


def test_cooldown_ladder_suppression_and_escalation() -> None:
    """Verify adaptive cooldown ladder suppresses frequent compaction and escalates duration."""
    config = HysteresisConfig(
        max_context_tokens=100000,
        high_watermark_ratio=0.85,
        low_watermark_ratio=0.50,
        emergency_watermark_ratio=0.95,
        base_cooldown_turns=5,
        ladder_escalation_step=2,
    )
    engine = HysteresisCompressionEngine(config)

    # Initial compaction occurs at turn 1
    eval_turn1 = engine.evaluate(current_tokens=86000, current_turn=1)
    assert eval_turn1.should_compress

    # Arm cooldown at turn 1
    activated_duration = engine.record_compression_success(current_turn=1)
    assert activated_duration == 5

    # During cooldown (turns 2 to 5), high watermark is suppressed
    for turn in range(2, 6):
        eval_mid = engine.evaluate(current_tokens=87000, current_turn=turn)
        assert not eval_mid.should_compress
        assert eval_mid.cooldown_suppressed
        status = engine.get_cooldown_status(current_turn=turn)
        assert status.is_in_cooldown
        assert status.remaining_turns == (6 - turn)

    # Cooldown expires at turn 6
    eval_turn6 = engine.evaluate(current_tokens=88000, current_turn=6)
    assert eval_turn6.should_compress
    assert not eval_turn6.cooldown_suppressed

    # Second compaction escalates cooldown: 5 + 1 * 2 = 7 turns
    second_cooldown = engine.record_compression_success(current_turn=6)
    assert second_cooldown == 7
    status_escalated = engine.get_cooldown_status(current_turn=6)
    assert status_escalated.remaining_turns == 7
    assert status_escalated.current_ladder_step == 2

    # Reset cleans cooldown ladder
    engine.reset_cooldown()
    status_reset = engine.get_cooldown_status(current_turn=6)
    assert not status_reset.is_in_cooldown
    assert status_reset.remaining_turns == 0


def test_emergency_overflow_overrides_cooldown() -> None:
    """Verify emergency overflow (>=95%) punches through cooldown ladder to prevent catastrophic OOM."""
    config = HysteresisConfig(
        max_context_tokens=100000,
        high_watermark_ratio=0.85,
        low_watermark_ratio=0.50,
        emergency_watermark_ratio=0.95,
        base_cooldown_turns=5,
    )
    engine = HysteresisCompressionEngine(config)

    # Turn 0 triggers compaction and arms 5-turn cooldown
    engine.record_compression_success(current_turn=0)

    # At turn 2, a giant tool call spikes context to 96%
    eval_emergency = engine.evaluate(current_tokens=96000, current_turn=2)
    assert eval_emergency.tier == WatermarkTier.EMERGENCY_OVERFLOW
    assert eval_emergency.should_compress
    assert eval_emergency.is_emergency
    assert not eval_emergency.cooldown_suppressed
    assert "Emergency watermark breach" in eval_emergency.decision_reason


def test_sanctuary_protection_and_zero_amnesia_compaction() -> None:
    """Verify genesis prompt, active todos, and diff anchors remain completely exempt from compaction."""
    config = HysteresisConfig(
        max_context_tokens=10000,
        high_watermark_ratio=0.80,
        low_watermark_ratio=0.40,
        bytes_per_token_estimate=4.0,
    )
    engine = HysteresisCompressionEngine(config)

    messages = [
        # Genesis directive (Turn 0) -> Sanctuary
        {
            "role": "system",
            "content": "You are Myrm Architect. Follow zero-any and 400-line limits strictly.",
        },
        # Middle turn with active checklist -> Sanctuary
        {
            "role": "user",
            "content": "Task Checklist:\n- [ ] Implement Hysteresis controller\n- [ ] Run full regression tests",
        },
        # Bulky middle chatter -> Should be compacted/stubbed
        {
            "role": "assistant",
            "content": "Detailed verbose thinking analysis log " * 40,
        },
        # Code diff anchor -> Sanctuary
        {
            "role": "assistant",
            "content": "diff --git a/engine.py b/engine.py\n@@ -1,5 +1,10 @@\n+added hysteresis line",
        },
        # Explicit sanctuary block
        {
            "role": "user",
            "content": "Important user decision: <sanctuary>Do not touch authentication tokens</sanctuary>",
        },
        # Bulky tool output -> Should be compacted/stubbed
        {
            "role": "tool",
            "content": "Large execution stdout " * 50,
        },
        # Tail turns (Recent 2 turns) -> Unconditionally protected
        {
            "role": "user",
            "content": "What is our current status?",
        },
        {
            "role": "assistant",
            "content": "We are validating the test suite.",
        },
    ]

    compacted_messages, report = engine.apply_hysteresis_compaction(
        messages=messages,
        current_turn=1,
        target_reclaim_tokens=400,
    )

    # 1. Sanctuary preservation
    assert report.sanctuary_blocks_count >= 4
    assert report.sanctuary_tokens_preserved > 0
    assert report.reclaimed_tokens > 0
    assert report.final_tokens < report.original_tokens

    compacted_contents = [m["content"] for m in compacted_messages]

    # Genesis prompt is 100% preserved
    assert "You are Myrm Architect. Follow zero-any and 400-line limits strictly." in compacted_contents[0]
    # Active checklist is 100% preserved
    assert any("- [ ] Implement Hysteresis controller" in c for c in compacted_contents)
    # Code diff is 100% preserved
    assert any("diff --git a/engine.py" in c for c in compacted_contents)
    # Explicit sanctuary is 100% preserved
    assert any("Do not touch authentication tokens" in c for c in compacted_contents)
    # Recent turns preserved
    assert "What is our current status?" in compacted_contents[-2]
    assert "We are validating the test suite." in compacted_contents[-1]

    # Bulky items turned into stub
    stubs = [c for c in compacted_contents if "[Compacted Context Turn" in c]
    assert len(stubs) >= 1
