"""Adaptive CPU and memory throttling watchdog for intensive sandbox workloads.

Benchmarked against host anti-lockup and OOM prevention invariants:
- Continuous evaluation of host CPU percentage and physical RAM watermark.
- Injects dynamic micro-sleep delays when CPU utilization exceeds 85% to cool down cores.
- Enforces strict concurrency serialization (concurrency = 1) when free RAM drops below 2GB.
- Outputs human-readable Markdown diagnostic alerts and structured WatchdogVerdicts.

[OUTPUT]
- AdaptiveThrottlingWatchdog: Core supervisor regulating pacing and concurrency.

[INPUT]
- __future__
- uuid

[OUTPUT]
- AdaptiveThrottlingWatchdog

[POS]
Adaptive CPU and memory throttling watchdog for intensive sandbox workloads.
"""

from __future__ import annotations

import uuid

from myrm_agent_harness.runtime.throttling_watchdog.throttling_types import (
    SystemLoadSnapshot,
    ThrottleAction,
    WatchdogVerdict,
)


class AdaptiveThrottlingWatchdog:
    """Supervises host resource consumption and regulates sandbox task pacing."""

    def __init__(
        self,
        cpu_critical_threshold_percent: float = 85.0,
        ram_critical_watermark_bytes: int = 2 * 1024 * 1024 * 1024,  # 2 GiB
        max_throttle_delay_seconds: float = 0.5,
        default_concurrency: int = 4,
    ) -> None:
        self.cpu_threshold = cpu_critical_threshold_percent
        self.ram_watermark = ram_critical_watermark_bytes
        self.max_delay = max_throttle_delay_seconds
        self.default_concurrency = default_concurrency

    def compute_dynamic_delay(self, cpu_percent: float) -> float:
        """Calculate dynamic sleep delay based on the degree of CPU threshold overrun."""
        if cpu_percent <= self.cpu_threshold:
            return 0.0
        delta = cpu_percent - self.cpu_threshold
        # Pacing scale: 0.02s per percentage point above threshold, capped at max_delay
        return min(self.max_delay, round(delta * 0.02, 3))

    def evaluate_system_load(self, snapshot: SystemLoadSnapshot) -> WatchdogVerdict:
        """Audit current host metrics and deliver an actionable pacing directive."""
        verdict_id = f"v_wd_{uuid.uuid4().hex[:8]}"

        # Priority 1: Low Memory Watermark (Highest danger: kernel panic / OOM killer)
        if snapshot.is_ram_critical:
            ram_mb = snapshot.available_ram_bytes // (1024 * 1024)
            return WatchdogVerdict(
                verdict_id=verdict_id,
                action=ThrottleAction.SERIALIZE_CONCURRENCY,
                applied_delay_seconds=0.1,
                max_allowed_concurrency=1,
                reason=(
                    f"可用物理内存 ({ram_mb} MB) 低于 2GB 安全水位线；"
                    f"已强制启用并发串行化排队，防止系统 OOM 崩溃。"
                ),
            )

        # Priority 2: CPU Saturation (Prevents desktop UI freezing and thermal throttling)
        if snapshot.is_cpu_critical:
            delay = self.compute_dynamic_delay(snapshot.cpu_percent)
            safe_concurrency = max(1, self.default_concurrency // 2)
            return WatchdogVerdict(
                verdict_id=verdict_id,
                action=ThrottleAction.THROTTLE_SLEEP,
                applied_delay_seconds=delay,
                max_allowed_concurrency=safe_concurrency,
                reason=(
                    f"宿主机 CPU 占用率达到 {snapshot.cpu_percent:.1f}% (超阈值 {self.cpu_threshold}%)；"
                    f"已注入 {delay}s 退避延迟并降低并发度至 {safe_concurrency}，保障桌面流畅响应。"
                ),
            )

        # Priority 3: Healthy / Normal operation
        return WatchdogVerdict(
            verdict_id=verdict_id,
            action=ThrottleAction.NO_ACTION,
            applied_delay_seconds=0.0,
            max_allowed_concurrency=self.default_concurrency,
            reason="宿主机资源负载正常，允许满速并发执行。",
        )

    def render_verdict_markdown(self, verdict: WatchdogVerdict) -> str:
        """Render a GitHub Flavored Markdown diagnostic status card for user inspection."""
        lines: list[str] = [
            "### 🛡️ 沙箱计算资源看门狗裁决卡片",
            f"- **裁决 ID**: `{verdict.verdict_id}`",
            f"- **调控动作**: `{verdict.action.value}`",
            f"- **注入退避延时**: `{verdict.applied_delay_seconds}s`",
            f"- **允许最大并发度**: `{verdict.max_allowed_concurrency}`",
            "",
        ]

        if verdict.action == ThrottleAction.SERIALIZE_CONCURRENCY:
            lines.extend(
                [
                    "> [!CAUTION]",
                    f"> **内存严重告警**：{verdict.reason}",
                    "",
                ]
            )
        elif verdict.action == ThrottleAction.THROTTLE_SLEEP:
            lines.extend(
                [
                    "> [!WARNING]",
                    f"> **CPU 高负载自适应退避**：{verdict.reason}",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> **正常运行**：{verdict.reason}",
                    "",
                ]
            )

        return "\n".join(lines)
