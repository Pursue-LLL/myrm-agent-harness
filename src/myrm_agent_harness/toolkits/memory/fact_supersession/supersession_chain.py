"""Engine managing fact lifecycle, explicit supersession chains, and valid-time interval queries.

[INPUT]
- toolkits.memory.fact_supersession.models::TemporalFactRecord, TemporalFactStatus (POS: Types and models for
  fact supersession.)

[OUTPUT]
- FactSupersessionChainEngine: Engine managing fact lifecycle, explicit supersession chains, and valid-time
  interval queries.

[POS]
Engine managing fact lifecycle, explicit supersession chains, and valid-time interval queries.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.fact_supersession.models import (
    TemporalFactRecord,
    TemporalFactStatus,
)


class FactSupersessionChainEngine:
    """Engine managing fact lifecycle, explicit supersession chains, and valid-time interval queries."""

    def __init__(self) -> None:
        self._facts: dict[str, TemporalFactRecord] = {}

    def record_fact(self, fact: TemporalFactRecord) -> TemporalFactRecord:
        """Register a new temporal fact into the store."""
        self._facts[fact.fact_id] = fact
        return fact

    def get_fact(self, fact_id: str) -> TemporalFactRecord | None:
        """Retrieve a specific fact by identifier."""
        return self._facts.get(fact_id)

    def supersede(
        self,
        old_fact_id: str,
        new_fact: TemporalFactRecord,
    ) -> tuple[TemporalFactRecord, TemporalFactRecord]:
        """Atomically link a supersession chain: close old fact valid-interval and record new fact."""
        old_fact = self._facts.get(old_fact_id)
        if not old_fact:
            raise KeyError(f"Target fact '{old_fact_id}' to supersede not found.")

        # Close old fact interval
        old_fact.valid_until = new_fact.valid_from
        old_fact.superseded_by = new_fact.fact_id
        old_fact.status = TemporalFactStatus.SUPERSEDED

        # Record new fact
        new_fact.status = TemporalFactStatus.ACTIVE
        new_fact.valid_until = None
        self._facts[new_fact.fact_id] = new_fact

        return old_fact, new_fact

    def query_active(
        self,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[TemporalFactRecord]:
        """Retrieve currently valid facts (valid_until IS NULL and status is ACTIVE)."""
        results: list[TemporalFactRecord] = []
        for fact in self._facts.values():
            if fact.status != TemporalFactStatus.ACTIVE or fact.valid_until is not None:
                continue
            if subject and fact.subject.lower() != subject.lower():
                continue
            if predicate and fact.predicate.lower() != predicate.lower():
                continue
            results.append(fact)
        return sorted(results, key=lambda f: f.valid_from, reverse=True)

    def query_as_of(
        self,
        point_in_time: str,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[TemporalFactRecord]:
        """Time-travel query retrieving facts valid as of a specific point in time."""
        results: list[TemporalFactRecord] = []
        for fact in self._facts.values():
            # Must have started on or before point_in_time
            if fact.valid_from > point_in_time:
                continue
            # Must not have expired before point_in_time
            if fact.valid_until is not None and fact.valid_until <= point_in_time:
                continue
            # Skip quarantined/archived facts
            if fact.status in (TemporalFactStatus.QUARANTINED, TemporalFactStatus.ARCHIVED):
                continue
            if subject and fact.subject.lower() != subject.lower():
                continue
            if predicate and fact.predicate.lower() != predicate.lower():
                continue
            results.append(fact)
        return sorted(results, key=lambda f: f.valid_from, reverse=True)

    def get_supersession_history(self, fact_id: str) -> list[TemporalFactRecord]:
        """Trace backward all ancestor facts that were superseded leading up to this fact."""
        target_fact = self._facts.get(fact_id)
        if not target_fact:
            return []

        ancestors: list[TemporalFactRecord] = []
        # Find who was superseded_by this fact_id
        current_id = fact_id
        while True:
            predecessor = None
            for f in self._facts.values():
                if f.superseded_by == current_id:
                    predecessor = f
                    break
            if predecessor:
                ancestors.append(predecessor)
                current_id = predecessor.fact_id
            else:
                break
        return ancestors

    def list_all_facts(self) -> list[TemporalFactRecord]:
        """Return all facts in descending order of creation time."""
        return sorted(list(self._facts.values()), key=lambda f: f.created_at, reverse=True)
