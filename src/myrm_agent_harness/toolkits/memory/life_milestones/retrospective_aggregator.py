"""Growth Retrospective Aggregator consolidating personal reflections into life journey cards.

Topic 01 Item 137: GrowthRetrospectiveAggregator.
Synthesizes non-utilitarian growth reflections, emotional journeys, and landmark milestones
into evocative retrospective cards for lifelong self-awareness.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.life_milestones.models import (
    GrowthDiaryEntry,
    PersonalRetrospectiveCard,
    PrivacyIntimacyLevel,
)
from myrm_agent_harness.toolkits.memory.life_milestones.timeline_engine import (
    LifeMilestonesEngine,
)
from myrm_agent_harness.toolkits.memory.life_milestones.value_alignment_projector import (
    ValueSystemAlignmentProjector,
)


class GrowthRetrospectiveAggregator:
    """Aggregates diary reflections, emotional trends, and milestones into human-readable retrospective cards."""

    def __init__(
        self,
        timeline_engine: LifeMilestonesEngine,
        value_projector: ValueSystemAlignmentProjector,
    ) -> None:
        self._timeline = timeline_engine
        self._value_projector = value_projector
        self._diaries: dict[str, GrowthDiaryEntry] = {}

    def record_diary_entry(self, entry: GrowthDiaryEntry) -> None:
        """Store a non-utilitarian growth reflection entry."""
        self._diaries[entry.entry_id] = entry

    def get_diary_entry(self, entry_id: str) -> GrowthDiaryEntry | None:
        """Fetch a specific diary entry."""
        return self._diaries.get(entry_id)

    def list_diaries(
        self,
        era_label: str | None = None,
        limit: int = 50,
    ) -> list[GrowthDiaryEntry]:
        """List diary entries sorted chronologically descending."""
        entries = list(self._diaries.values())
        if era_label:
            entries = [e for e in entries if e.era_label == era_label]
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def list_diary_entries(
        self,
        era_label: str | None = None,
        limit: int = 50,
    ) -> list[GrowthDiaryEntry]:
        """Alias for list_diaries."""
        return self.list_diaries(era_label=era_label, limit=limit)

    def generate_retrospective_card(
        self,
        era_label: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> PersonalRetrospectiveCard:
        """Synthesize a reflective life retrospective card for a specific era or timeframe."""
        # 1. Retrieve milestones in this era/timeframe
        milestones = self._timeline.list_milestones(
            max_intimacy=PrivacyIntimacyLevel.INTIMATE_PERSONAL,
            start_year=start_year,
            end_year=end_year,
        )

        milestone_highlights: list[str] = [
            f"{m.year}年: {m.title}（{m.narrative}）" for m in milestones[:6]
        ]
        if not milestone_highlights:
            milestone_highlights = ["平稳沉淀，内敛蓄力，生活在平静中徐徐展开。"]

        # 2. Retrieve dominant active values
        active_values = self._value_projector.get_active_values()
        dominant_values: list[str] = [
            f"{v.theme}: {v.current_stance}" for v in active_values[:5]
        ]
        if not dominant_values:
            dominant_values = ["在探索与经历中持续淬炼个人生活哲学。"]

        # 3. Retrieve growth reflections from diaries
        matching_diaries = [
            d for d in self._diaries.values()
            if (era_label is None or d.era_label == era_label) or
            (start_year is not None and d.timestamp.year >= start_year and (end_year is None or d.timestamp.year <= end_year))
        ]
        matching_diaries.sort(key=lambda d: d.timestamp)

        growth_reflections: list[str] = [
            f"[{d.emotional_state}] {d.reflection_text}" for d in matching_diaries[:5]
        ]
        if not growth_reflections:
            growth_reflections = ["岁月静好，步履不停，每一次自省都是灵魂向内生长的印记。"]

        time_span = f"{start_year} - {end_year if end_year else '至今'}" if start_year else "人生岁月印记"

        companion_note = (
            f"在【{era_label}】这一人生旅程中，你经历了从探索到笃定的转变。"
            f"所有经历的大事与心境感悟，共同铸就了今天独特的你。我很荣幸作为你的个人 AI 伙伴，"
            f"陪伴并见证这段真实而丰沛的生命历程。"
        )

        return PersonalRetrospectiveCard(
            era_label=era_label,
            time_span=time_span,
            milestone_highlights=milestone_highlights,
            dominant_values=dominant_values,
            growth_reflections=growth_reflections,
            companion_empathy_note=companion_note,
        )
