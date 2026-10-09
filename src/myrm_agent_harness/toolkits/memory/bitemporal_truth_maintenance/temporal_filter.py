"""Bitemporal filtering engine and snapshot projection.

[POS]
Applies temporal criteria and justification requirements to execute as-of queries,
filtering out retracted facts and unsupported inferences to ensure prompt context purity.

[INPUT]
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.EvidenceRecord
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.EvidenceType
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.TemporalQueryCriteria
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.TruthMaintenanceSnapshot
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.support_graph.TruthMaintenanceGraph

[OUTPUT]
- BitemporalFilterEngine
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models import (
    EvidenceRecord,
    EvidenceType,
    TemporalQueryCriteria,
    TruthMaintenanceSnapshot,
)
from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.support_graph import (
    TruthMaintenanceGraph,
)


class BitemporalFilterEngine:
    """Evaluates temporal query criteria against a TruthMaintenanceGraph."""

    def filter_records(
        self,
        graph: TruthMaintenanceGraph,
        criteria: TemporalQueryCriteria,
    ) -> list[EvidenceRecord]:
        """Filters graph records matching bitemporal coordinates and active support rules.

        Args:
            graph: Source truth maintenance graph.
            criteria: Query constraints including valid time, known time, and support rules.

        Returns:
            Filtered list of evidence records sorted by confidence descending.
        """
        now = time.time()
        valid_t = now if criteria.as_of_valid_time is None else criteria.as_of_valid_time
        known_t = now if criteria.as_of_known_time is None else criteria.as_of_known_time

        results: list[EvidenceRecord] = []

        for record in graph.all_records():
            # 1. Filter by evidence type if specified
            if criteria.evidence_types and record.evidence_type not in criteria.evidence_types:
                continue

            # 2. Filter by confidence threshold
            if record.confidence < criteria.min_confidence:
                continue

            # 3. Filter by temporal validity and justification support
            if criteria.require_active_support:
                is_active = graph.is_record_active_at(
                    record.evidence_id,
                    valid_time=valid_t,
                    known_time=known_t,
                )
            else:
                is_active = record.is_valid_and_known(
                    valid_time=valid_t,
                    known_time=known_t,
                )

            if is_active:
                results.append(record)

        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    def create_snapshot(
        self,
        graph: TruthMaintenanceGraph,
        as_of_valid_time: float,
        as_of_known_time: float,
    ) -> TruthMaintenanceSnapshot:
        """Projects a comprehensive snapshot separating active vs invalidated entities.

        Args:
            graph: Source truth maintenance graph.
            as_of_valid_time: Target temporal coordinate in real-world timeline.
            as_of_known_time: Target transaction coordinate in belief timeline.

        Returns:
            TruthMaintenanceSnapshot containing distinct active and invalidated groups.
        """
        active_evidences: list[EvidenceRecord] = []
        retracted_evidences: list[EvidenceRecord] = []
        active_inferences: list[EvidenceRecord] = []
        invalidated_inferences: list[EvidenceRecord] = []

        for record in graph.all_records():
            is_primitive = record.evidence_type in (
                EvidenceType.FACT,
                EvidenceType.OBSERVATION,
            )

            if is_primitive:
                if record.is_retracted(as_of_known_time):
                    retracted_evidences.append(record)
                elif record.is_valid_and_known(as_of_valid_time, as_of_known_time):
                    active_evidences.append(record)
            else:
                # Derived inference or decision
                if graph.is_record_active_at(
                    record.evidence_id,
                    valid_time=as_of_valid_time,
                    known_time=as_of_known_time,
                ):
                    active_inferences.append(record)
                else:
                    invalidated_inferences.append(record)

        return TruthMaintenanceSnapshot(
            active_evidences=tuple(active_evidences),
            retracted_evidences=tuple(retracted_evidences),
            active_inferences=tuple(active_inferences),
            invalidated_inferences=tuple(invalidated_inferences),
            as_of_valid_time=as_of_valid_time,
            as_of_known_time=as_of_known_time,
        )
