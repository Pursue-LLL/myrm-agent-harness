"""Projector augmenting recalled facts with their historical supersession lineage for explainability.

[INPUT]
- toolkits.memory.fact_supersession.models::DialecticRecallProjection, TemporalFactRecord (POS: Types and
  models for fact supersession.)
- toolkits.memory.fact_supersession.supersession_chain::FactSupersessionChainEngine (POS: Engine managing fact
  lifecycle, explicit supersession chains, and valid-time interval queries.)

[OUTPUT]
- DialecticRecallProjector: Projector augmenting recalled facts with their historical supersession lineage for
  explainability.

[POS]
Projector augmenting recalled facts with their historical supersession lineage for explainability.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.fact_supersession.models import (
    DialecticRecallProjection,
    TemporalFactRecord,
)
from myrm_agent_harness.toolkits.memory.fact_supersession.supersession_chain import (
    FactSupersessionChainEngine,
)


class DialecticRecallProjector:
    """Projector augmenting recalled facts with their historical supersession lineage for explainability."""

    def project_recall(
        self,
        chain_engine: FactSupersessionChainEngine,
        subject: str | None = None,
        predicate: str | None = None,
        as_of_time: str | None = None,
    ) -> DialecticRecallProjection:
        """Execute point-in-time or current recall, attaching ancestral supersession history."""
        if as_of_time:
            active_facts = chain_engine.query_as_of(
                point_in_time=as_of_time,
                subject=subject,
                predicate=predicate,
            )
        else:
            active_facts = chain_engine.query_active(
                subject=subject,
                predicate=predicate,
            )

        lineage_map: dict[str, list[TemporalFactRecord]] = {}
        for fact in active_facts:
            ancestors = chain_engine.get_supersession_history(fact.fact_id)
            if ancestors:
                lineage_map[fact.fact_id] = ancestors

        return DialecticRecallProjection(
            active_facts=active_facts,
            superseded_lineage=lineage_map,
            as_of_time=as_of_time,
            total_matched=len(active_facts),
        )
