"""Unit tests for Active-Turn Live Context Compression and Token Pressure Dashboard Suite.

Validates slash command /compress detection, TokenPressureGauge telemetry,
lossless anchor preservation, and structured middle trajectory folding.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.active_compression import (
    ActiveCompressionConfig,
    ActiveContextCompressionEngine,
    CompressTriggerKind,
    TokenPressureGauge,
    TokenPressureLevel,
)


def test_is_compress_command_detection() -> None:
    """Verifies that slash commands requesting compaction are reliably recognized."""
    assert ActiveContextCompressionEngine.is_compress_command("/compress") is True
    assert ActiveContextCompressionEngine.is_compress_command("/compact") is True
    assert ActiveContextCompressionEngine.is_compress_command("/compress now") is True
    assert ActiveContextCompressionEngine.is_compress_command("/compact now") is True
    assert ActiveContextCompressionEngine.is_compress_command("  /COMPRESS  ") is True

    # Negative cases
    assert ActiveContextCompressionEngine.is_compress_command("hello world") is False
    assert ActiveContextCompressionEngine.is_compress_command("can you compress this file?") is False
    assert ActiveContextCompressionEngine.is_compress_command("") is False


def test_token_pressure_gauge_levels_and_telemetry() -> None:
    """Verifies token pressure gauge correctly classifies watermarks and computes latency."""
    cfg = ActiveCompressionConfig(context_limit=100000)

    # 1. Normal level (30k / 100k = 30%)
    snap_normal = TokenPressureGauge.measure(30000, cfg)
    assert snap_normal.pressure_level == TokenPressureLevel.NORMAL
    assert snap_normal.recommend_compression is False
    assert snap_normal.usage_ratio == 0.30
    assert snap_normal.estimated_latency_seconds < 3.5

    # 2. Moderate level (60k / 100k = 60%)
    snap_mod = TokenPressureGauge.measure(60000, cfg)
    assert snap_mod.pressure_level == TokenPressureLevel.MODERATE
    assert snap_mod.recommend_compression is False

    # 3. High level (80k / 100k = 80%)
    snap_high = TokenPressureGauge.measure(80000, cfg)
    assert snap_high.pressure_level == TokenPressureLevel.HIGH
    assert snap_high.recommend_compression is True
    assert "建议点击压缩" in snap_high.status_text

    # 4. Critical level (95k / 100k = 95%)
    snap_crit = TokenPressureGauge.measure(95000, cfg)
    assert snap_crit.pressure_level == TokenPressureLevel.CRITICAL
    assert snap_crit.recommend_compression is True
    assert "上下文已达到极限" in snap_crit.status_text


def test_active_compression_execution_and_anchor_preservation() -> None:
    """Verifies that middle turns are folded into snapshot while head and tail are strictly preserved."""
    cfg = ActiveCompressionConfig(keep_head_turns=1, keep_tail_turns=2)
    engine = ActiveContextCompressionEngine(config=cfg)

    # Construct conversation history
    # Head turn: System instruction with anchor identity
    head_msg = {
        "role": "system",
        "content": "You are a senior principal systems architect. Follow MEMORY.md strictly.",
    }

    # Middle turns: 10 verbose tool execution calls
    middle_msgs: list[dict[str, str]] = []
    for i in range(10):
        middle_msgs.append({
            "role": "user",
            "content": f"Investigate cluster node status #{i + 1} and report memory footprint.",
        })
        middle_msgs.append({
            "role": "tool",
            "content": f"Output from kubectl describe pod #{i + 1}: " + "x" * 600,
        })
        middle_msgs.append({
            "role": "assistant",
            "content": f"Node #{i + 1} is healthy with stable memory consumption.",
        })

    # Tail turns: latest exchange
    tail_user = {
        "role": "user",
        "content": "Now proceed to verify the storage volumes.",
    }
    tail_assistant = {
        "role": "assistant",
        "content": "Proceeding to examine storage volumes now.",
    }

    full_conversation: list[dict[str, str]] = [head_msg] + middle_msgs + [tail_user, tail_assistant]

    # Execute compression
    result = engine.execute_compression(
        messages=full_conversation,
        trigger_kind=CompressTriggerKind.USER_EXPLICIT_SLASH,
    )

    assert result.is_compressed is True
    assert result.trigger_kind == CompressTriggerKind.USER_EXPLICIT_SLASH
    assert result.original_tokens > result.compacted_tokens
    # Significant token reduction achieved
    assert result.reclaim_ratio > 0.50
    assert result.reclaimed_tokens > 1000

    # Verify head is perfectly preserved
    compacted_msgs = result.compacted_messages
    assert compacted_msgs[0] == head_msg

    # Verify middle folded summary is placed after head
    assert compacted_msgs[1]["role"] == "system"
    assert "[ACTIVE CONTEXT RECLAIMED STATE SNAPSHOT]" in compacted_msgs[1]["content"]

    # Verify tail messages are intact
    assert compacted_msgs[-2] == tail_user
    assert compacted_msgs[-1] == tail_assistant
    assert result.preserved_tail_count == 2
    assert result.frozen_head_count == 1


def test_active_compression_short_history_bypass() -> None:
    """Verifies that brief message history that does not warrant folding is safely bypassed."""
    cfg = ActiveCompressionConfig(keep_head_turns=1, keep_tail_turns=2)
    engine = ActiveContextCompressionEngine(config=cfg)

    short_conversation = [
        {"role": "system", "content": "You are an assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    result = engine.execute_compression(short_conversation)
    assert result.is_compressed is False
    assert result.reclaimed_tokens == 0
    assert len(result.compacted_messages) == 3
