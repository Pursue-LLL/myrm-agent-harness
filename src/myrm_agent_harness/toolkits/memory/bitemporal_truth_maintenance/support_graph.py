"""Justification support graph and truth maintenance evaluation engine.

[POS]
Maintains causal justification dependencies between premises and derived inferences.
Executes non-destructive retraction and recursive active support verification.

[INPUT]
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.BitemporalCoordinates
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.EvidenceRecord
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.EvidenceType
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.SupportDependency
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.TimeInterval

[OUTPUT]
- TruthMaintenanceGraph
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models import (
    BitemporalCoordinates,
    EvidenceRecord,
    EvidenceType,
    SupportDependency,
    TimeInterval,
)


class TruthMaintenanceGraph:
    """Graph structure managing bitemporal evidence and justification links."""

    def __init__(self) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._dependencies: dict[str, list[SupportDependency]] = {}
        self._dependents: dict[str, set[str]] = {}

    @property
    def record_count(self) -> int:
        """Total number of evidence and inference records registered."""
        return len(self._records)

    def add_record(self, record: EvidenceRecord) -> None:
        """Registers or replaces an evidence record in the graph."""
        self._records[record.evidence_id] = record

    def get_record(self, evidence_id: str) -> EvidenceRecord | None:
        """Retrieves a specific evidence record by ID, or None if absent."""
        return self._records.get(evidence_id)

    def all_records(self) -> list[EvidenceRecord]:
        """Returns a snapshot list of all records in the graph."""
        return list(self._records.values())

    def retract_record(self, evidence_id: str, retracted_at: float) -> bool:
        """Non-destructively retracts an evidence record by closing its known_interval.

        Preserves physical historical data while invalidating ongoing temporal validity.

        Args:
            evidence_id: Identifier of the record to retract.
            retracted_at: Transaction timestamp at which retraction took effect.

        Returns:
            True if record was found and newly retracted, False if already retracted or not found.
        """
        record = self._records.get(evidence_id)
        if record is None:
            return False

        current_known = record.bitemporal.known_interval
        if current_known.end is not None and current_known.end <= retracted_at:
            # Already retracted earlier or at same time
            return False

        new_known = TimeInterval(start=current_known.start, end=retracted_at)
        updated_coords = BitemporalCoordinates(
            valid_interval=record.bitemporal.valid_interval,
            known_interval=new_known,
        )
        updated_record = EvidenceRecord(
            evidence_id=record.evidence_id,
            content=record.content,
            evidence_type=record.evidence_type,
            bitemporal=updated_coords,
            confidence=record.confidence,
            metadata=dict(record.metadata),
        )
        self._records[evidence_id] = updated_record
        return True

    def add_support_dependency(self, dependency: SupportDependency) -> None:
        """Registers a causal support justification link from premises to an inference."""
        inf_id = dependency.inference_id
        if inf_id not in self._dependencies:
            self._dependencies[inf_id] = []
        self._dependencies[inf_id].append(dependency)

        for premise_id in dependency.premise_ids:
            if premise_id not in self._dependents:
                self._dependents[premise_id] = set()
            self._dependents[premise_id].add(inf_id)

    def get_dependencies_for(self, inference_id: str) -> list[SupportDependency]:
        """Returns all registered support justifications for a given inference."""
        return list(self._dependencies.get(inference_id, []))

    def get_dependents_of(self, premise_id: str) -> set[str]:
        """Returns IDs of all inferences that directly depend on the given premise."""
        return set(self._dependents.get(premise_id, set()))

    def has_active_support(
        self,
        inference_id: str,
        valid_time: float,
        known_time: float,
        visited: set[str] | None = None,
    ) -> bool:
        """Recursively evaluates if an inference holds active justification support.

        An inference has active support if at least one justification exists wherein
        ALL supporting premise records are active at (valid_time, known_time).
        """
        cycle_guard = set() if visited is None else set(visited)
        if inference_id in cycle_guard:
            # Detected circular reasoning loop: unsupported
            return False
        cycle_guard.add(inference_id)

        justifications = self._dependencies.get(inference_id)
        if not justifications:
            # Derived node without any registered justifications cannot stand
            return False

        for just in justifications:
            if not just.premise_ids:
                continue
            all_premises_active = True
            for premise_id in just.premise_ids:
                if not self.is_record_active_at(
                    premise_id,
                    valid_time=valid_time,
                    known_time=known_time,
                    visited=cycle_guard,
                ):
                    all_premises_active = False
                    break
            if all_premises_active:
                return True

        return False

    def is_record_active_at(
        self,
        evidence_id: str,
        valid_time: float,
        known_time: float,
        visited: set[str] | None = None,
    ) -> bool:
        """Evaluates whether an evidence record or inference is active at bitemporal point."""
        record = self._records.get(evidence_id)
        if record is None:
            return False

        if not record.is_valid_and_known(valid_time=valid_time, known_time=known_time):
            return False

        # If it's a derived inference or decision, check underlying justification support
        if record.evidence_type in (EvidenceType.INFERENCE, EvidenceType.DECISION):
            return self.has_active_support(
                evidence_id,
                valid_time=valid_time,
                known_time=known_time,
                visited=visited,
            )

        return True

    def calculate_causal_distance(self, inference_id: str) -> int:
        """Calculates maximum causal distance from ground facts to this inference."""
        justifications = self._dependencies.get(inference_id)
        if not justifications:
            return 1

        max_dist = 1
        for just in justifications:
            premise_dists = [
                self.calculate_causal_distance(pid)
                for pid in just.premise_ids
                if pid in self._records
                and self._records[pid].evidence_type == EvidenceType.INFERENCE
            ]
            if premise_dists:
                dist = max(premise_dists) + just.causal_distance
            else:
                dist = just.causal_distance
            if dist > max_dist:
                max_dist = dist
        return max_dist
