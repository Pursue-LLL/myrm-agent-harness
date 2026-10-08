"""Realtime context health gauge calculating window usage, headroom, and savings metrics.

[INPUT]
- ContextHealthConfig, ContextSavingsMetrics, ContextUsageSnapshot, HealthWatermarkLevel, ToolExpenditureItem.

[OUTPUT]
- RealtimeHealthGauge: Mathematical engine evaluating capacity watermarks and savings ratios.

[POS]
Calculation and metrics evaluation layer for context health dashboard.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .context_health_types import (
    ContextHealthConfig,
    ContextSavingsMetrics,
    ContextUsageSnapshot,
    HealthWatermarkLevel,
    ToolExpenditureItem,
)


class RealtimeHealthGauge:
    """Calculates context window saturation, tool payload rankings, and compression savings."""

    def __init__(self, config: ContextHealthConfig | None = None) -> None:
        self._config = config or ContextHealthConfig()

    def evaluate_health(
        self,
        session_id: str,
        current_tokens: int,
        raw_offloaded_tokens: int = 0,
        tool_stats: Mapping[str, tuple[int, int]] | None = None,
        custom_window_capacity: int | None = None,
    ) -> ContextUsageSnapshot:
        """Computes current context utilization, headroom, tool shares, and savings ratio."""
        capacity = custom_window_capacity or self._config.default_window_capacity
        usage_ratio = current_tokens / capacity if capacity > 0 else 1.0
        usage_pct = round(usage_ratio * 100.0, 1)

        # 1. Determine watermark level
        if usage_ratio >= 1.0:
            level = HealthWatermarkLevel.OVERFLOW
        elif usage_ratio >= self._config.critical_watermark_ratio:
            level = HealthWatermarkLevel.CRITICAL
        elif usage_ratio >= self._config.warning_watermark_ratio:
            level = HealthWatermarkLevel.WARNING
        else:
            level = HealthWatermarkLevel.HEALTHY

        safe_headroom = max(0, capacity - current_tokens)

        # 2. Tool consumption breakdown
        top_tools = self._aggregate_tool_expenditures(tool_stats or {})

        # 3. Calculate context savings
        savings = self._calculate_savings(
            resident_tokens=current_tokens,
            offloaded_tokens=raw_offloaded_tokens,
        )

        return ContextUsageSnapshot(
            session_id=session_id,
            current_tokens=current_tokens,
            window_capacity_tokens=capacity,
            usage_percentage=usage_pct,
            safe_headroom_tokens=safe_headroom,
            watermark_level=level,
            top_tools=top_tools,
            savings=savings,
        )

    def render_compact_health_card(self, snapshot: ContextUsageSnapshot) -> str:
        """Renders compact, model-readable context health card for prompt injection or UI status."""
        lines: list[str] = [
            "<context_health>",
            f"Usage: {snapshot.current_tokens:,} / {snapshot.window_capacity_tokens:,} tokens ({snapshot.usage_percentage}% - {snapshot.watermark_level.value.upper()})",
            f"Headroom: {snapshot.safe_headroom_tokens:,} tokens safe margin",
        ]

        if snapshot.savings.raw_unbounded_tokens > snapshot.savings.context_resident_tokens:
            lines.append(
                f"Savings: {snapshot.savings.savings_ratio_pct}% saved ({snapshot.savings.savings_multiplier_x}x multiplier | {snapshot.savings.tokens_saved:,} tokens offloaded)"
            )

        if snapshot.top_tools:
            lines.append("Top Tool Hotspots:")
            for item in snapshot.top_tools[:3]:
                lines.append(
                    f"- {item.tool_name}: {item.call_count} calls, ~{item.token_estimate:,} tokens ({item.share_percentage}%)"
                )

        if snapshot.watermark_level in (HealthWatermarkLevel.WARNING, HealthWatermarkLevel.CRITICAL, HealthWatermarkLevel.OVERFLOW):
            lines.append(f"⚠️ [CAPACITY ALERT] Window reaches {snapshot.usage_percentage}%. Active compaction recommended.")

        lines.append("</context_health>")
        return "\n".join(lines)

    def _aggregate_tool_expenditures(
        self,
        tool_stats: Mapping[str, tuple[int, int]],
    ) -> Sequence[ToolExpenditureItem]:
        """tool_stats mapping: {tool_name: (call_count, total_raw_chars)}"""
        if not tool_stats:
            return ()

        items: list[tuple[str, int, int, int]] = []
        total_tokens_across_tools = 0

        for name, (count, chars) in tool_stats.items():
            token_est = max(1, (chars + 3) // 4)
            items.append((name, count, chars, token_est))
            total_tokens_across_tools += token_est

        result: list[ToolExpenditureItem] = []
        # Sort descending by token estimate
        items.sort(key=lambda x: x[3], reverse=True)

        for name, count, chars, tokens in items[: self._config.top_tools_limit]:
            share = round((tokens / total_tokens_across_tools * 100.0), 1) if total_tokens_across_tools > 0 else 0.0
            result.append(
                ToolExpenditureItem(
                    tool_name=name,
                    call_count=count,
                    raw_chars=chars,
                    token_estimate=tokens,
                    share_percentage=share,
                )
            )

        return tuple(result)

    def _calculate_savings(
        self,
        resident_tokens: int,
        offloaded_tokens: int,
    ) -> ContextSavingsMetrics:
        raw_total = resident_tokens + offloaded_tokens
        saved = max(0, offloaded_tokens)

        if raw_total > 0 and saved > 0:
            ratio = round((saved / raw_total) * 100.0, 1)
            multiplier = round(raw_total / max(1, resident_tokens), 1)
        else:
            ratio = 0.0
            multiplier = 1.0

        return ContextSavingsMetrics(
            raw_unbounded_tokens=raw_total,
            context_resident_tokens=resident_tokens,
            tokens_saved=saved,
            savings_ratio_pct=ratio,
            savings_multiplier_x=multiplier,
        )
