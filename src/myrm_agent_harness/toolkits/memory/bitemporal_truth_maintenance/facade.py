"""Public facade and unified interface for bitemporal truth maintenance.

[POS]
Orchestrates truth maintenance graph, bitemporal intervals, and filtering engine.
Provides high-level helpers for recording facts, deriving inferences, and querying active states.

[INPUT]
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.support_graph
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.temporal_filter

[OUTPUT]
- BitemporalTruthMaintenanceFacade
- get_bitemporal_truth_maintenance_facade
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models import (
    BitemporalCoordinates,
    EvidenceRecord,
    EvidenceType,
    SupportDependency,
    TemporalQueryCriteria,
    TimeInterval,
    TruthMaintenanceSnapshot,
)
from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.support_graph import (
    TruthMaintenanceGraph,
)
from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.temporal_filter import (
    BitemporalFilterEngine,
)


class BitemporalTruthMaintenanceFacade:
    """Unified entrypoint for bitemporal evidence and justification reasoning."""

    def __init__(
        self,
        graph: TruthMaintenanceGraph | None = None,
        filter_engine: BitemporalFilterEngine | None = None,
    ) -> None:
        self._graph = graph or TruthMaintenanceGraph()
        self._filter_engine = filter_engine or BitemporalFilterEngine()

    @property
    def graph(self) -> TruthMaintenanceGraph:
        """Direct accessor to internal truth maintenance graph."""
        return self._graph

    def record_fact(
        self,
        evidence_id: str,
        content: str,
        valid_start: float,
        valid_end: float | None = None,
        known_start: float | None = None,
        confidence: float = 1.0,
        metadata: dict[str, str] | None = None,
    ) -> EvidenceRecord:
        """Records an external ground fact with bitemporal boundaries."""
        now = time.time()
        k_start = now if known_start is None else known_start
        coords = BitemporalCoordinates(
            valid_interval=TimeInterval(start=valid_start, end=valid_end),
            known_interval=TimeInterval(start=k_start, end=None),
        )
        record = EvidenceRecord(
            evidence_id=evidence_id,
            content=content,
            evidence_type=EvidenceType.FACT,
            bitemporal=coords,
            confidence=confidence,
            metadata=dict(metadata or {}),
        )
        self._graph.add_record(record)
        return record

    def record_observation(
        self,
        evidence_id: str,
        content: str,
        observed_at: float,
        confidence: float = 1.0,
        metadata: dict[str, str] | None = None,
    ) -> EvidenceRecord:
        """Records an instantaneous point observation as an unclosed fact."""
        return self.record_fact(
            evidence_id=evidence_id,
            content=content,
            valid_start=observed_at,
            valid_end=None,
            known_start=observed_at,
            confidence=confidence,
            metadata=metadata,
        )

    def derive_inference(
        self,
        inference_id: str,
        content: str,
        premise_ids: list[str],
        justification: str,
        valid_start: float | None = None,
        valid_end: float | None = None,
        known_start: float | None = None,
        causal_distance: int = 1,
        confidence: float = 1.0,
        metadata: dict[str, str] | None = None,
    ) -> EvidenceRecord:
        """Derives an inference supported by premise justifications."""
        now = time.time()
        v_start = now if valid_start is None else valid_start
        k_start = now if known_start is None else known_start

        coords = BitemporalCoordinates(
            valid_interval=TimeInterval(start=v_start, end=valid_end),
            known_interval=TimeInterval(start=k_start, end=None),
        )

        meta = dict(metadata or {})
        meta["causal_distance"] = str(causal_distance)
        meta["justification"] = justification

        record = EvidenceRecord(
            evidence_id=inference_id,
            content=content,
            evidence_type=EvidenceType.INFERENCE,
            bitemporal=coords,
            confidence=confidence,
            metadata=meta,
        )
        self._graph.add_record(record)

        dependency = SupportDependency(
            inference_id=inference_id,
            premise_ids=tuple(premise_ids),
            causal_distance=causal_distance,
            justification=justification,
        )
        self._graph.add_support_dependency(dependency)
        return record

    def retract_record(self, evidence_id: str, retracted_at: float | None = None) -> bool:
        """Non-destructively marks an evidence record as retracted."""
        now = time.time()
        r_time = now if retracted_at is None else retracted_at
        return self._graph.retract_record(evidence_id, retracted_at=r_time)

    def query_active(self, criteria: TemporalQueryCriteria) -> list[EvidenceRecord]:
        """Queries records adhering to specified bitemporal constraints and active support."""
        return self._filter_engine.filter_records(self._graph, criteria)

    def project_snapshot(
        self,
        as_of_valid_time: float | None = None,
        as_of_known_time: float | None = None,
    ) -> TruthMaintenanceSnapshot:
        """Projects a point-in-time snapshot separating active vs invalidated entities."""
        now = time.time()
        v_time = now if as_of_valid_time is None else as_of_valid_time
        k_time = now if as_of_known_time is None else as_of_known_time
        return self._filter_engine.create_snapshot(
            self._graph,
            as_of_valid_time=v_time,
            as_of_known_time=k_time,
        )


_GLOBAL_FACADE: BitemporalTruthMaintenanceFacade | None = None


def get_bitemporal_truth_maintenance_facade() -> BitemporalTruthMaintenanceFacade:
    """Returns singleton instance of BitemporalTruthMaintenanceFacade."""
    global _GLOBAL_FACADE
    if _GLOBAL_FACADE is None:
        _GLOBAL_FACADE = BitemporalTruthMaintenanceFacade()
    return _GLOBAL_FACADE
