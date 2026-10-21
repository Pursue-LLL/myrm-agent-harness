"""Lineage and version manager for derived memory observations.

[INPUT]
- external_providers.models::{DerivedObservationRecord, EvidenceRecord, MemoryLifecycleStage, MemoryScopeContext, SupersedesRecord}

[OUTPUT]
- CascadeDeletionResult: summary of atomic cascaded cleanup.
- SupersedesLineageManager: manager for observations, version chains, scopes, and cascade cleanups.

[POS]
Provides bidirectional lineage tracking between immutable evidence and derived observations.
Governs explicit supersedes version progressions and atomic cascade cleanup across representations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.external_providers.models import (
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryLifecycleStage,
    MemoryScopeContext,
    SupersedesRecord,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CascadeDeletionResult:
    """Summary of cascaded deletion execution across representations."""

    target_observation_id: str
    deleted_observation_ids: tuple[str, ...]
    unlinked_evidence_ids: tuple[str, ...]
    invalidated_cache_keys: tuple[str, ...]
    affected_version_nodes: int


class SupersedesLineageManager:
    """Governs evidence-observation links, supersedes version chains, and scope isolation."""

    def __init__(self) -> None:
        self._evidences: dict[str, EvidenceRecord] = {}
        self._observations: dict[str, DerivedObservationRecord] = {}
        self._supersedes_links: dict[str, SupersedesRecord] = {}
        self._evidence_to_observations: dict[str, set[str]] = {}
        self._graph_relation_ids: dict[str, set[str]] = {}
        self._vector_index_ids: dict[str, set[str]] = {}

    def record_evidence(self, evidence: EvidenceRecord) -> None:
        """Register an immutable raw evidence turn."""
        self._evidences[evidence.evidence_id] = evidence
        if evidence.evidence_id not in self._evidence_to_observations:
            self._evidence_to_observations[evidence.evidence_id] = set()

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        """Retrieve an immutable evidence record by ID."""
        return self._evidences.get(evidence_id)

    def publish_observation(self, observation: DerivedObservationRecord) -> None:
        """Store or publish a derived observation record and update evidence mappings."""
        self._observations[observation.observation_id] = observation
        for evid in observation.supporting_evidence_ids:
            if evid in self._evidences:
                self._evidence_to_observations.setdefault(evid, set()).add(observation.observation_id)

    def get_observation(self, observation_id: str) -> DerivedObservationRecord | None:
        """Retrieve a derived observation by ID."""
        return self._observations.get(observation_id)

    def associate_external_indices(
        self,
        observation_id: str,
        graph_edge_ids: Sequence[str] = (),
        vector_ids: Sequence[str] = (),
    ) -> None:
        """Associate external graph relations and vector IDs for cascade cleanup."""
        if graph_edge_ids:
            self._graph_relation_ids.setdefault(observation_id, set()).update(graph_edge_ids)
        if vector_ids:
            self._vector_index_ids.setdefault(observation_id, set()).update(vector_ids)

    def supersede_observation(
        self,
        old_observation_id: str,
        new_observation: DerivedObservationRecord,
        reason: str,
    ) -> SupersedesRecord:
        """Supersede an older observation with a new version, updating lineage pointers."""
        old_obs = self._observations.get(old_observation_id)
        if old_obs is None:
            raise KeyError(f"Target observation not found for superseding: {old_observation_id}")

        updated_old = DerivedObservationRecord(
            observation_id=old_obs.observation_id,
            scope=old_obs.scope,
            content=old_obs.content,
            category=old_obs.category,
            status=MemoryLifecycleStage.SUPERSEDE,
            supporting_evidence_ids=old_obs.supporting_evidence_ids,
            proof_count=old_obs.proof_count,
            confidence=old_obs.confidence,
            freshness=old_obs.freshness,
            supersedes_id=old_obs.supersedes_id,
            superseded_by=new_observation.observation_id,
            created_at=old_obs.created_at,
            updated_at=_utc_now(),
        )
        self._observations[old_observation_id] = updated_old

        validated_new = DerivedObservationRecord(
            observation_id=new_observation.observation_id,
            scope=new_observation.scope,
            content=new_observation.content,
            category=new_observation.category,
            status=new_observation.status,
            supporting_evidence_ids=new_observation.supporting_evidence_ids,
            proof_count=new_observation.proof_count,
            confidence=new_observation.confidence,
            freshness=new_observation.freshness,
            supersedes_id=old_observation_id,
            superseded_by=None,
            created_at=new_observation.created_at,
            updated_at=_utc_now(),
        )
        self.publish_observation(validated_new)

        record = SupersedesRecord(
            current_id=new_observation.observation_id,
            previous_id=old_observation_id,
            reason=reason,
            superseded_at=_utc_now(),
        )
        self._supersedes_links[new_observation.observation_id] = record
        return record

    def get_lineage_chain(self, observation_id: str) -> tuple[DerivedObservationRecord, ...]:
        """Traverse the version lineage chain backwards from latest to earliest root."""
        chain: list[DerivedObservationRecord] = []
        curr_id: str | None = observation_id
        visited: set[str] = set()

        while curr_id and curr_id not in visited:
            visited.add(curr_id)
            obs = self._observations.get(curr_id)
            if obs is None:
                break
            chain.append(obs)
            curr_id = obs.supersedes_id

        return tuple(chain)

    def rollback_to_version(
        self,
        current_observation_id: str,
        target_version_id: str,
        reason: str,
    ) -> DerivedObservationRecord:
        """Roll back an observation lineage to a prior version, creating an active rollback node."""
        chain = self.get_lineage_chain(current_observation_id)
        target = next((item for item in chain if item.observation_id == target_version_id), None)
        if target is None:
            raise ValueError(f"Version {target_version_id} not found in lineage of {current_observation_id}")

        new_id = f"{target_version_id}_rb_{int(_utc_now().timestamp())}"
        rollback_obs = DerivedObservationRecord(
            observation_id=new_id,
            scope=target.scope,
            content=target.content,
            category=target.category,
            status=MemoryLifecycleStage.PUBLISH,
            supporting_evidence_ids=target.supporting_evidence_ids,
            proof_count=target.proof_count,
            confidence=target.confidence,
            freshness=_utc_now(),
            supersedes_id=current_observation_id,
            superseded_by=None,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        self.supersede_observation(
            old_observation_id=current_observation_id,
            new_observation=rollback_obs,
            reason=f"Rollback to {target_version_id}: {reason}",
        )
        return rollback_obs

    def cascade_delete(self, observation_id: str) -> CascadeDeletionResult:
        """Atomically delete an observation and cascade-clean evidence references, graphs, and vectors."""
        target = self._observations.get(observation_id)
        if target is None:
            return CascadeDeletionResult(
                target_observation_id=observation_id,
                deleted_observation_ids=(),
                unlinked_evidence_ids=(),
                invalidated_cache_keys=(),
                affected_version_nodes=0,
            )

        deleted_ids: list[str] = [observation_id]
        unlinked_evids: list[str] = []
        invalidated_keys: list[str] = []

        for evid in target.supporting_evidence_ids:
            obs_set = self._evidence_to_observations.get(evid)
            if obs_set and observation_id in obs_set:
                obs_set.remove(observation_id)
                unlinked_evids.append(evid)

        if observation_id in self._graph_relation_ids:
            for gid in self._graph_relation_ids.pop(observation_id):
                invalidated_keys.append(f"graph:{gid}")

        if observation_id in self._vector_index_ids:
            for vid in self._vector_index_ids.pop(observation_id):
                invalidated_keys.append(f"vector:{vid}")

        self._observations.pop(observation_id, None)
        self._supersedes_links.pop(observation_id, None)

        return CascadeDeletionResult(
            target_observation_id=observation_id,
            deleted_observation_ids=tuple(deleted_ids),
            unlinked_evidence_ids=tuple(unlinked_evids),
            invalidated_cache_keys=tuple(invalidated_keys),
            affected_version_nodes=1,
        )

    def filter_by_scope(
        self,
        scope: MemoryScopeContext,
        include_superseded: bool = False,
    ) -> tuple[DerivedObservationRecord, ...]:
        """Apply pre-retrieval physical scope filtering strictly before returning observations."""
        results: list[DerivedObservationRecord] = []
        for obs in self._observations.values():
            if not include_superseded and obs.status in (
                MemoryLifecycleStage.SUPERSEDE,
                MemoryLifecycleStage.EXPIRE,
            ):
                continue
            if scope.matches(obs.scope):
                results.append(obs)
        return tuple(results)
