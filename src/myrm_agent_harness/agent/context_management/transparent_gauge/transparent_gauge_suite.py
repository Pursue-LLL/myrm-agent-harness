"""Main suite orchestrating transparent context window gauge and 5-segment budget breakdown.

[INPUT]
- session_id: str identifier of current conversation session
- window_capacity_tokens: int total context window size (e.g. 128000 or 200000)
- reserve_headroom_tokens: int tokens reserved for output safety headroom

[OUTPUT]
- ContextWindowTransparentGaugeAndBudgetBreakdownSuite: Main orchestrator for transparent gauge analysis and intervention.

[POS]
Main suite orchestrating transparent context window gauge and 5-segment budget breakdown.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from .budget_analyzer import BudgetAnalyzer
from .gauge_types import (
    BudgetSegmentBreakdown,
    BudgetSegmentKind,
    CompactionAdjustmentIntervention,
    TransparentGaugeReceipt,
    WatermarkAlertLevel,
    WatermarkState,
)


class ContextWindowTransparentGaugeAndBudgetBreakdownSuite:
    """Main suite providing 5-segment context window visibility and proactive compaction control."""

    def __init__(
        self,
        session_id: str,
        window_capacity_tokens: int = 128000,
        reserve_headroom_tokens: int = 16384,
    ) -> None:
        self._session_id = session_id
        self._window_capacity_tokens = window_capacity_tokens
        self._reserve_headroom_tokens = reserve_headroom_tokens

        self._system_tokens: int = 0
        self._rules_tokens: int = 0
        self._skills_tokens: int = 0
        self._summary_tokens: int = 0
        self._active_turns_tokens: int = 0

        self._interventions: List[CompactionAdjustmentIntervention] = []
        self._pinned_segments: List[str] = []

    @property
    def session_id(self) -> str:
        """Return session ID."""
        return self._session_id

    @property
    def window_capacity_tokens(self) -> int:
        """Return context window capacity."""
        return self._window_capacity_tokens

    def update_system_instructions(self, text: str) -> None:
        """Update system instructions text and calculate token count."""
        self._system_tokens = BudgetAnalyzer.estimate_tokens_from_text(text)

    def update_workspace_rules(self, text: str) -> None:
        """Update workspace rules text (e.g. AGENTS.md) and calculate token count."""
        self._rules_tokens = BudgetAnalyzer.estimate_tokens_from_text(text)

    def update_dynamic_skills(self, skills_content_list: List[str]) -> None:
        """Update mounted skills content list and aggregate token count."""
        total = sum(BudgetAnalyzer.estimate_tokens_from_text(item) for item in skills_content_list)
        self._skills_tokens = total

    def update_compacted_summary(self, summary_text: str) -> None:
        """Update historical compacted summary text and calculate token count."""
        self._summary_tokens = BudgetAnalyzer.estimate_tokens_from_text(summary_text)

    def record_active_turn_content(self, text: str) -> None:
        """Incrementally add active turn text to active turns token count."""
        self._active_turns_tokens += BudgetAnalyzer.estimate_tokens_from_text(text)

    def set_segment_tokens_directly(
        self,
        segment: BudgetSegmentKind,
        token_count: int,
    ) -> None:
        """Directly inject verified token count for a specific segment."""
        count = max(0, token_count)
        if segment == BudgetSegmentKind.SYSTEM_INSTRUCTIONS:
            self._system_tokens = count
        elif segment == BudgetSegmentKind.WORKSPACE_RULES:
            self._rules_tokens = count
        elif segment == BudgetSegmentKind.DYNAMIC_SKILLS:
            self._skills_tokens = count
        elif segment == BudgetSegmentKind.COMPACTED_SUMMARY:
            self._summary_tokens = count
        elif segment == BudgetSegmentKind.ACTIVE_TURNS:
            self._active_turns_tokens = count

    def pin_segment(self, segment_id: str) -> None:
        """Pin a specific critical segment to prevent compaction trimming."""
        if segment_id not in self._pinned_segments:
            self._pinned_segments.append(segment_id)

    def apply_intervention(
        self,
        intervention: CompactionAdjustmentIntervention,
    ) -> TransparentGaugeReceipt:
        """Apply user or developer manual compaction intervention."""
        self._interventions.append(intervention)
        for seg_id in intervention.pinned_segment_ids:
            self.pin_segment(seg_id)
        return self.generate_gauge_receipt()

    def trigger_preemptive_compaction(self, reason: str = "User requested early compaction") -> TransparentGaugeReceipt:
        """Convenience method to manually trigger preemptive compaction."""
        intervention = CompactionAdjustmentIntervention(
            preemptive_compaction_requested=True,
            reason=reason,
        )
        return self.apply_intervention(intervention)

    def compute_current_breakdown(self) -> BudgetSegmentBreakdown:
        """Calculate and return 5-segment budget breakdown."""
        return BudgetAnalyzer.analyze_budget(
            system_instructions_tokens=self._system_tokens,
            workspace_rules_tokens=self._rules_tokens,
            dynamic_skills_tokens=self._skills_tokens,
            compacted_summary_tokens=self._summary_tokens,
            active_turns_tokens=self._active_turns_tokens,
            window_capacity_tokens=self._window_capacity_tokens,
            reserve_headroom_tokens=self._reserve_headroom_tokens,
        )

    def evaluate_current_watermark(self) -> WatermarkState:
        """Evaluate current saturation level and recommendations."""
        breakdown = self.compute_current_breakdown()
        return BudgetAnalyzer.evaluate_watermark(breakdown)

    def generate_gauge_receipt(self) -> TransparentGaugeReceipt:
        """Produce an auditable snapshot receipt of current budget breakdown."""
        breakdown = self.compute_current_breakdown()
        watermark = BudgetAnalyzer.evaluate_watermark(breakdown)
        return TransparentGaugeReceipt(
            receipt_id=f"tgr_{uuid.uuid4().hex[:8]}",
            session_id=self._session_id,
            breakdown=breakdown,
            watermark=watermark,
            active_interventions_count=len(self._interventions),
            snapshot_timestamp_iso=datetime.now(timezone.utc).isoformat(),
        )
