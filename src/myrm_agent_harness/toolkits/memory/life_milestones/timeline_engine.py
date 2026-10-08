"""Macro Life Timeline Engine managing lifelong chronological milestones and era segmentation.

[INPUT]
- memory.life_milestones.models::{LifeMilestone, LifeStageEra, MilestoneCategory, PrivacyIntimacyLevel} (POS: Data contracts of the life milestones package)
- memory.life_milestones.significance_gate::MilestoneSignificanceGate (POS: Intake filter of the life milestones package)

[OUTPUT]
- LifeMilestonesEngine: in-memory store that records a milestone only when the gate admits it, lists milestones chronologically with category, year and privacy-ceiling filters, extracts turning points by significance, and registers eras and finds the era of a year

[POS]
Chronological milestone store of the life milestones package. Read by the value projector and the retrospective aggregator.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.life_milestones.models import (
    LifeMilestone,
    LifeStageEra,
    MilestoneCategory,
    PrivacyIntimacyLevel,
)
from myrm_agent_harness.toolkits.memory.life_milestones.significance_gate import (
    MilestoneSignificanceGate,
)


class LifeMilestonesEngine:
    """Manages the chronological topology of major human life milestones across decades."""

    def __init__(
        self,
        gate: MilestoneSignificanceGate | None = None,
    ) -> None:
        self._gate = gate or MilestoneSignificanceGate()
        self._milestones: dict[str, LifeMilestone] = {}
        self._eras: dict[str, LifeStageEra] = {}

    def register_era(self, era: LifeStageEra) -> None:
        """Register or update a macro lifecycle era segment."""
        self._eras[era.era_id] = era

    def record_milestone(
        self,
        milestone: LifeMilestone,
        is_user_explicit: bool = True,
    ) -> tuple[bool, str | None]:
        """Verify via significance gate and record milestone chronologically."""
        gate_res = self._gate.evaluate(
            title=milestone.title,
            narrative=milestone.narrative,
            category=milestone.category,
            significance_hint=milestone.significance_score,
            is_user_explicit=is_user_explicit,
            intimacy_level=milestone.intimacy_level,
        )

        if not gate_res.is_admitted:
            return False, gate_res.rejection_reason

        self._milestones[milestone.milestone_id] = milestone
        return True, None

    def get_milestone(self, milestone_id: str) -> LifeMilestone | None:
        """Fetch a specific milestone by unique ID."""
        return self._milestones.get(milestone_id)

    def delete_milestone(self, milestone_id: str) -> bool:
        """Remove a milestone by ID."""
        if milestone_id in self._milestones:
            del self._milestones[milestone_id]
            return True
        return False

    def list_milestones(
        self,
        category: MilestoneCategory | None = None,
        max_intimacy: PrivacyIntimacyLevel = PrivacyIntimacyLevel.OPEN_OVERVIEW,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[LifeMilestone]:
        """List milestones sorted chronologically with boundary filters."""
        allowed_intimacy = self._get_allowed_intimacy_levels(max_intimacy)
        results: list[LifeMilestone] = []

        for ms in self._milestones.values():
            if ms.intimacy_level not in allowed_intimacy:
                continue
            if category is not None and ms.category != category:
                continue
            if start_year is not None and ms.year < start_year:
                continue
            if end_year is not None and ms.year > end_year:
                continue
            results.append(ms)

        # Sort chronologically by year, then by timestamp_str
        results.sort(key=lambda m: (m.year, m.timestamp_str))
        return results

    def list_eras(self) -> list[LifeStageEra]:
        """List all lifecycle era segments sorted chronologically."""
        eras = list(self._eras.values())
        eras.sort(key=lambda e: e.start_year)
        return eras

    def get_era_for_year(self, year: int) -> LifeStageEra | None:
        """Find the applicable era segment corresponding to a given year."""
        for era in self._eras.values():
            if era.start_year <= year and (era.end_year is None or year <= era.end_year):
                return era
        return None

    def get_turning_points(
        self,
        min_significance: float = 0.85,
        max_intimacy: PrivacyIntimacyLevel = PrivacyIntimacyLevel.INTIMATE_PERSONAL,
    ) -> list[LifeMilestone]:
        """Extract high-significance life turning points (career shifts, relocations, value awakenings)."""
        allowed_intimacy = self._get_allowed_intimacy_levels(max_intimacy)
        turning_points: list[LifeMilestone] = [
            ms for ms in self._milestones.values()
            if ms.significance_score >= min_significance and ms.intimacy_level in allowed_intimacy
        ]
        turning_points.sort(key=lambda m: (m.year, m.timestamp_str))
        return turning_points

    def total_count(self) -> int:
        """Total number of recorded milestones."""
        return len(self._milestones)

    @staticmethod
    def _get_allowed_intimacy_levels(max_level: PrivacyIntimacyLevel) -> set[PrivacyIntimacyLevel]:
        """Resolve permitted intimacy levels up to the specified boundary."""
        if max_level == PrivacyIntimacyLevel.OPEN_OVERVIEW:
            return {PrivacyIntimacyLevel.OPEN_OVERVIEW}
        if max_level == PrivacyIntimacyLevel.INTIMATE_PERSONAL:
            return {PrivacyIntimacyLevel.OPEN_OVERVIEW, PrivacyIntimacyLevel.INTIMATE_PERSONAL}
        return {
            PrivacyIntimacyLevel.OPEN_OVERVIEW,
            PrivacyIntimacyLevel.INTIMATE_PERSONAL,
            PrivacyIntimacyLevel.CONFIDENTIAL_RESTRICTED,
        }
