"""Unit tests for ProcessPriorityGuard and AdaptiveThrottlingWatchdog.

Tests benchmarked against Doubao host anti-lockup and OOM prevention invariants:
1. Process priority guard and exception-safe graceful degradation.
2. Normal host load passthrough with zero pacing overhead.
3. High CPU saturation dynamic micro-sleep delay and concurrency reduction.
4. Low RAM watermark forced concurrency serialization to avoid kernel OOM panic.
"""

from __future__ import annotations

import os

from myrm_agent_harness.runtime.throttling_watchdog import (
    AdaptiveThrottlingWatchdog,
    ProcessPriorityGuard,
    ProcessPriorityLevel,
    SystemLoadSnapshot,
    ThrottleAction,
)


def test_process_priority_guard() -> None:
    """Test process priority degradation and exception-safe fallback behavior."""
    current_pid = os.getpid()

    # Attempt setting priority to BACKGROUND_LOW
    res = ProcessPriorityGuard.apply_background_nice(current_pid)
    # The return value depends on OS capabilities and privileges, but must never raise
    assert isinstance(res, bool)

    # Calling with invalid negative pid should safely return False without crashing
    safe_fail = ProcessPriorityGuard.set_priority(-9999, ProcessPriorityLevel.IDLE_LOWEST)
    assert safe_fail is False


def test_adaptive_throttling_normal_load() -> None:
    """Test normal load state allows unhindered concurrency with zero delay."""
    watchdog = AdaptiveThrottlingWatchdog(
        cpu_critical_threshold_percent=85.0,
        ram_critical_watermark_bytes=2 * 1024 * 1024 * 1024,
        default_concurrency=4,
    )

    snapshot = SystemLoadSnapshot.capture(
        cpu_percent=45.0,
        available_ram_bytes=16 * 1024 * 1024 * 1024,  # 16 GiB
    )

    assert snapshot.is_cpu_critical is False
    assert snapshot.is_ram_critical is False

    verdict = watchdog.evaluate_system_load(snapshot)
    assert verdict.action == ThrottleAction.NO_ACTION
    assert verdict.applied_delay_seconds == 0.0
    assert verdict.max_allowed_concurrency == 4

    md = watchdog.render_verdict_markdown(verdict)
    assert "### 🛡️ 沙箱计算资源看门狗裁决卡片" in md
    assert "> [!NOTE]" in md
    assert "允许满速并发执行" in md


def test_adaptive_throttling_cpu_saturation() -> None:
    """Test high CPU usage triggers dynamic micro-sleep delay and concurrency halving."""
    watchdog = AdaptiveThrottlingWatchdog(
        cpu_critical_threshold_percent=85.0,
        default_concurrency=4,
    )

    # CPU at 95% (10% over 85% threshold -> 10 * 0.02 = 0.20s delay)
    snapshot = SystemLoadSnapshot.capture(
        cpu_percent=95.0,
        available_ram_bytes=8 * 1024 * 1024 * 1024,
    )

    assert snapshot.is_cpu_critical is True
    assert snapshot.is_ram_critical is False

    verdict = watchdog.evaluate_system_load(snapshot)
    assert verdict.action == ThrottleAction.THROTTLE_SLEEP
    assert verdict.applied_delay_seconds == 0.20
    assert verdict.max_allowed_concurrency == 2

    md = watchdog.render_verdict_markdown(verdict)
    assert "> [!WARNING]" in md
    assert "CPU 高负载自适应退避" in md
    assert "95.0%" in md


def test_adaptive_throttling_ram_critical_watermark() -> None:
    """Test low available memory triggers immediate serialization of concurrency to 1."""
    watchdog = AdaptiveThrottlingWatchdog(
        ram_critical_watermark_bytes=2 * 1024 * 1024 * 1024,  # 2 GiB
        default_concurrency=8,
    )

    # Available RAM is 1 GiB (< 2 GiB watermark)
    snapshot = SystemLoadSnapshot.capture(
        cpu_percent=20.0,
        available_ram_bytes=1 * 1024 * 1024 * 1024,
    )

    assert snapshot.is_ram_critical is True

    verdict = watchdog.evaluate_system_load(snapshot)
    assert verdict.action == ThrottleAction.SERIALIZE_CONCURRENCY
    assert verdict.max_allowed_concurrency == 1
    assert verdict.applied_delay_seconds > 0.0

    md = watchdog.render_verdict_markdown(verdict)
    assert "> [!CAUTION]" in md
    assert "内存严重告警" in md
    assert "强制启用并发串行化排队" in md
