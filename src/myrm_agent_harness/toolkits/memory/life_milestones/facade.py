"""Unified facade for Life Milestones and Personal Timeline Suite.

[INPUT]
- memory.life_milestones.timeline_engine::LifeMilestonesEngine (POS: Chronological milestone store of the life milestones package)
- memory.life_milestones.significance_gate::MilestoneSignificanceGate (POS: Intake filter of the life milestones package)
- memory.life_milestones.value_alignment_projector::ValueSystemAlignmentProjector (POS: Value projection step of the life milestones package)
- memory.life_milestones.retrospective_aggregator::GrowthRetrospectiveAggregator (POS: Retrospective synthesis step of the life milestones package)
- memory.life_milestones.models::{ContextProjectionBundle, GrowthDiaryEntry, LifeMilestone, LifeStageEra, MilestoneCategory, PersonalRetrospectiveCard, PrivacyIntimacyLevel, ValueSystemNode} (POS: Data contracts of the life milestones package)

[OUTPUT]
- LifeMilestonesSuite: wires the gate, timeline, projector and aggregator (each injectable) behind milestone, era, value, diary, projection and retrospective operations plus counter statistics

[POS]
Single entry point of the life milestones package. Wires the components for hosts and the server's life milestones provider.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.life_milestones.models import (
    ContextProjectionBundle,
    GrowthDiaryEntry,
    LifeMilestone,
    LifeStageEra,
    MilestoneCategory,
    PersonalRetrospectiveCard,
    PrivacyIntimacyLevel,
    ValueSystemNode,
)
from myrm_agent_harness.toolkits.memory.life_milestones.retrospective_aggregator import (
    GrowthRetrospectiveAggregator,
)
from myrm_agent_harness.toolkits.memory.life_milestones.significance_gate import (
    MilestoneSignificanceGate,
)
from myrm_agent_harness.toolkits.memory.life_milestones.timeline_engine import (
    LifeMilestonesEngine,
)
from myrm_agent_harness.toolkits.memory.life_milestones.value_alignment_projector import (
    ValueSystemAlignmentProjector,
)


class LifeMilestonesSuite:
    """Unified facade orchestrating life milestones, evolving values, and reflective diaries."""

    def __init__(
        self,
        gate: MilestoneSignificanceGate | None = None,
        timeline_engine: LifeMilestonesEngine | None = None,
        value_projector: ValueSystemAlignmentProjector | None = None,
        retrospective_aggregator: GrowthRetrospectiveAggregator | None = None,
    ) -> None:
        self._gate = gate or MilestoneSignificanceGate()
        self._timeline = timeline_engine or LifeMilestonesEngine(gate=self._gate)
        self._value_projector = value_projector or ValueSystemAlignmentProjector(
            timeline_engine=self._timeline
        )
        self._retrospective = retrospective_aggregator or GrowthRetrospectiveAggregator(
            timeline_engine=self._timeline,
            value_projector=self._value_projector,
        )

    # 1. Milestone Operations
    def record_milestone(
        self,
        milestone: LifeMilestone,
        is_user_explicit: bool = True,
    ) -> tuple[bool, str | None]:
        """Verify and record a life milestone."""
        return self._timeline.record_milestone(milestone, is_user_explicit=is_user_explicit)

    def get_milestone(self, milestone_id: str) -> LifeMilestone | None:
        """Fetch a milestone by ID."""
        return self._timeline.get_milestone(milestone_id)

    def delete_milestone(self, milestone_id: str) -> bool:
        """Remove a milestone by ID."""
        return self._timeline.delete_milestone(milestone_id)

    def list_milestones(
        self,
        category: MilestoneCategory | None = None,
        max_intimacy: PrivacyIntimacyLevel = PrivacyIntimacyLevel.OPEN_OVERVIEW,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[LifeMilestone]:
        """List chronological milestones matching boundaries."""
        return self._timeline.list_milestones(
            category=category,
            max_intimacy=max_intimacy,
            start_year=start_year,
            end_year=end_year,
        )

    def get_turning_points(
        self,
        min_significance: float = 0.85,
        max_intimacy: PrivacyIntimacyLevel = PrivacyIntimacyLevel.INTIMATE_PERSONAL,
    ) -> list[LifeMilestone]:
        """Fetch top life turning points."""
        return self._timeline.get_turning_points(
            min_significance=min_significance,
            max_intimacy=max_intimacy,
        )

    # 2. Era Management
    def register_era(self, era: LifeStageEra) -> None:
        """Register a macro life stage era."""
        self._timeline.register_era(era)

    def list_eras(self) -> list[LifeStageEra]:
        """List all lifecycle era segments."""
        return self._timeline.list_eras()

    # 3. Value System Evolution
    def register_value(self, node: ValueSystemNode) -> None:
        """Register a value belief."""
        self._value_projector.register_value(node)

    def evolve_value(
        self,
        new_node: ValueSystemNode,
        prior_node_id: str | None = None,
    ) -> None:
        """Evolve a value belief into a new stance with causal linkage."""
        self._value_projector.evolve_value(new_node, prior_node_id=prior_node_id)

    def list_active_values(self) -> list[ValueSystemNode]:
        """List all currently active value beliefs."""
        return self._value_projector.get_active_values()

    # 4. Growth Diary
    def record_diary(self, entry: GrowthDiaryEntry) -> None:
        """Record a non-utilitarian growth reflection diary entry."""
        self._retrospective.record_diary_entry(entry)

    def list_diaries(
        self,
        era_label: str | None = None,
        limit: int = 50,
    ) -> list[GrowthDiaryEntry]:
        """List diary entries chronologically descending."""
        return self._retrospective.list_diaries(era_label=era_label, limit=limit)

    # 5. Projection & Retrospective Synthesis
    def project_context(
        self,
        query_text: str,
        max_intimacy: PrivacyIntimacyLevel = PrivacyIntimacyLevel.INTIMATE_PERSONAL,
        force_projection: bool = False,
    ) -> ContextProjectionBundle:
        """Project empathetic worldview and milestones into conversational context."""
        return self._value_projector.project_context(
            query_text=query_text,
            max_intimacy=max_intimacy,
            force_projection=force_projection,
        )

    def generate_retrospective_card(
        self,
        era_label: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> PersonalRetrospectiveCard:
        """Synthesize a reflective life retrospective card."""
        return self._retrospective.generate_retrospective_card(
            era_label=era_label,
            start_year=start_year,
            end_year=end_year,
        )

    # 6. Observability
    def get_stats(self) -> dict[str, int]:
        """Aggregate statistical metrics for telemetry."""
        return {
            "total_milestones": self._timeline.total_count(),
            "total_eras": len(self._timeline.list_eras()),
            "active_values": len(self.list_active_values()),
            "total_diaries": len(self.list_diaries(limit=10000)),
        }
