"""Types and data structures for transparent context window gauge and 5-segment budget breakdown.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- BudgetSegmentKind: Classification of 5 distinct token consumption zones.
- WatermarkAlertLevel: Alert level based on context window utilization threshold.
- BudgetSegmentBreakdown: Detailed token accounting across all 5 segments and headroom.
- WatermarkState: Current watermark evaluation containing alert level and action recommendations.
- CompactionAdjustmentIntervention: User/developer manual intervention directive.
- TransparentGaugeReceipt: Auditable receipt representing transparent gauge snapshot.

[POS]
Types and data structures for transparent context window gauge and 5-segment budget breakdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class BudgetSegmentKind(str, Enum):
    """Classification of context token consumption segments."""

    SYSTEM_INSTRUCTIONS = "system_instructions"
    WORKSPACE_RULES = "workspace_rules"
    DYNAMIC_SKILLS = "dynamic_skills"
    COMPACTED_SUMMARY = "compacted_summary"
    ACTIVE_TURNS = "active_turns"


class WatermarkAlertLevel(str, Enum):
    """Graduated watermark alert levels for proactive compaction awareness."""

    NORMAL = "normal"              # < 70%
    ATTENTION = "attention"        # 70% - 85%
    CRITICAL_WARN = "critical_warn" # 85% - 95%
    OVERFLOW_RISK = "overflow_risk" # >= 95%


@dataclass(frozen=True)
class BudgetSegmentBreakdown:
    """Detailed token accounting across 5 segments and total headroom."""

    system_instructions_tokens: int
    workspace_rules_tokens: int
    dynamic_skills_tokens: int
    compacted_summary_tokens: int
    active_turns_tokens: int
    total_used_tokens: int
    window_capacity_tokens: int
    reserve_headroom_tokens: int
    remaining_available_tokens: int
    utilization_ratio: float

    def get_segment_percentages(self) -> Dict[str, float]:
        """Calculate percentage contribution of each segment relative to total capacity."""
        if self.window_capacity_tokens <= 0:
            return {}
        cap = float(self.window_capacity_tokens)
        return {
            BudgetSegmentKind.SYSTEM_INSTRUCTIONS.value: round((self.system_instructions_tokens / cap) * 100, 2),
            BudgetSegmentKind.WORKSPACE_RULES.value: round((self.workspace_rules_tokens / cap) * 100, 2),
            BudgetSegmentKind.DYNAMIC_SKILLS.value: round((self.dynamic_skills_tokens / cap) * 100, 2),
            BudgetSegmentKind.COMPACTED_SUMMARY.value: round((self.compacted_summary_tokens / cap) * 100, 2),
            BudgetSegmentKind.ACTIVE_TURNS.value: round((self.active_turns_tokens / cap) * 100, 2),
        }


@dataclass(frozen=True)
class WatermarkState:
    """Evaluation of context window saturation state."""

    alert_level: WatermarkAlertLevel
    utilization_percentage: float
    is_compaction_recommended: bool
    recommended_action: str


@dataclass(frozen=True)
class CompactionAdjustmentIntervention:
    """Manual intervention directive submitted by developer/UI to fine-tune context."""

    preemptive_compaction_requested: bool = False
    custom_retained_tail_turns: Optional[int] = None
    pinned_segment_ids: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass(frozen=True)
class TransparentGaugeReceipt:
    """Snapshot receipt providing complete transparency into context budget allocation."""

    receipt_id: str
    session_id: str
    breakdown: BudgetSegmentBreakdown
    watermark: WatermarkState
    active_interventions_count: int
    snapshot_timestamp_iso: str
