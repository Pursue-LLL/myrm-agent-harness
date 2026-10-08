"""Calculation engine for context window 5-segment budget breakdown and watermark detection.

[INPUT]
- segment inputs (system text, rules text, skills metadata, summaries, active messages)
- window_capacity_tokens: int total context window size
- reserve_headroom_tokens: int safety margin reserved for generation

[OUTPUT]
- BudgetAnalyzer: Static and instance methods computing token breakdown and watermark status.

[POS]
Calculation engine for context window 5-segment budget breakdown and watermark detection.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from .gauge_types import (
    BudgetSegmentBreakdown,
    BudgetSegmentKind,
    WatermarkAlertLevel,
    WatermarkState,
)


class BudgetAnalyzer:
    """Computes exact token allocations across 5 distinct context segments and evaluates watermark levels."""

    @classmethod
    def estimate_tokens_from_text(cls, text: str) -> int:
        """Heuristic token estimation based on UTF-8 character length (approx 4 chars/token)."""
        if not text:
            return 0
        return max(1, math.ceil(len(text) / 4))

    @classmethod
    def analyze_budget(
        cls,
        system_instructions_tokens: int,
        workspace_rules_tokens: int,
        dynamic_skills_tokens: int,
        compacted_summary_tokens: int,
        active_turns_tokens: int,
        window_capacity_tokens: int,
        reserve_headroom_tokens: int = 16384,
    ) -> BudgetSegmentBreakdown:
        """Synthesize 5-segment breakdown and remaining headroom."""
        total_used = (
            system_instructions_tokens
            + workspace_rules_tokens
            + dynamic_skills_tokens
            + compacted_summary_tokens
            + active_turns_tokens
        )
        safe_capacity = max(1, window_capacity_tokens)
        remaining = max(0, window_capacity_tokens - total_used - reserve_headroom_tokens)
        utilization = min(1.0, round(float(total_used) / float(safe_capacity), 4))

        return BudgetSegmentBreakdown(
            system_instructions_tokens=system_instructions_tokens,
            workspace_rules_tokens=workspace_rules_tokens,
            dynamic_skills_tokens=dynamic_skills_tokens,
            compacted_summary_tokens=compacted_summary_tokens,
            active_turns_tokens=active_turns_tokens,
            total_used_tokens=total_used,
            window_capacity_tokens=window_capacity_tokens,
            reserve_headroom_tokens=reserve_headroom_tokens,
            remaining_available_tokens=remaining,
            utilization_ratio=utilization,
        )

    @classmethod
    def evaluate_watermark(
        cls,
        breakdown: BudgetSegmentBreakdown,
    ) -> WatermarkState:
        """Evaluate context saturation watermark and formulate proactive intervention advice."""
        utilization_pct = round(breakdown.utilization_ratio * 100, 2)

        if utilization_pct >= 95.0:
            level = WatermarkAlertLevel.OVERFLOW_RISK
            rec = True
            action = "Immediate compaction required: Context is in critical overflow danger."
        elif utilization_pct >= 85.0:
            level = WatermarkAlertLevel.CRITICAL_WARN
            rec = True
            action = "Proactive compaction strongly recommended: Window approaching reserve headroom."
        elif utilization_pct >= 70.0:
            level = WatermarkAlertLevel.ATTENTION
            rec = False
            action = "Normal monitoring: Window above 70%, consider trimming large tool responses if needed."
        else:
            level = WatermarkAlertLevel.NORMAL
            rec = False
            action = "Healthy capacity: Headroom is well within safe operating margins."

        return WatermarkState(
            alert_level=level,
            utilization_percentage=utilization_pct,
            is_compaction_recommended=rec,
            recommended_action=action,
        )
