"""Tests for pluggable external memory provider lifecycle and supersedes lineage pack.

[INPUT]
- external_providers.models::{
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryLifecycleStage,
    MemoryScopeContext,
    MemoryScopeType,
    ProviderKind,
  }
- external_providers.protocols::{
    ExternalMemoryProviderProtocol,
  }
- external_providers.lineage_manager::{
    SupersedesLineageManager,
  }
- external_providers.scheduler::{
    SingleActiveProviderScheduler,
    is_trivial_prompt,
  }
- external_providers.benchmark_suite::{
    ExternalMemoryBenchmarkSuite,
  }

[OUTPUT]
- Unit test suite verifying 5-stage lifecycle, circuit-breaking, supersedes lineage, scope isolation, and 3D benchmarks.

[POS]
Unit test suite verifying the external memory provider lifecycle contract and lineage governance.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.external_providers import (
    DerivedObservationRecord,
    EvidenceRecord,
    ExternalMemoryBenchmarkSuite,
    MemoryLifecycleStage,
    MemoryScopeContext,
    MemoryScopeType,
    ProviderKind,
    SingleActiveProviderScheduler,
    SupersedesLineageManager,
    is_trivial_prompt,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockExternalProvider:
    """Mock external memory provider conforming to ExternalMemoryProviderProtocol."""

    def __init__(
        self,
        name: str = "mock_hindsight",
        kind: ProviderKind = ProviderKind.HINDSIGHT,
        sleep_ms: int = 0,
    ) -> None:
        self._name: str = name
        self._kind: ProviderKind = kind
        self._sleep_ms: int = sleep_ms
        self.synced_evidences: list[EvidenceRecord] = []
        self.mirrored_records: list[DerivedObservationRecord] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> ProviderKind:
        return self._kind

    def is_available(self) -> bool:
        return True

    async def prefetch(
        self,
        session_id: str,
        query: str,
        scope: MemoryScopeContext,
    ) -> Sequence[DerivedObservationRecord]:
        if self._sleep_ms > 0:
            await asyncio.sleep(self._sleep_ms / 1000.0)
        return (
            DerivedObservationRecord(
                observation_id=f"{self._name}_obs_1",
                scope=scope,
                content=f"External insight for {query}",
                category="architecture",
                status=MemoryLifecycleStage.PUBLISH,
                supporting_evidence_ids=("ev_ext_01",),
                proof_count=1,
                confidence=0.9,
                freshness=_utc_now(),
            ),
        )

    def format_inject(
        self,
        observations: Sequence[DerivedObservationRecord],
    ) -> str:
        items = "\n".join(f"- [{obs.category}] {obs.content}" for obs in observations)
        return f"<external_recalled_memory>\n{items}\n</external_recalled_memory>"

    async def sync_turn(self, evidence: EvidenceRecord) -> None:
        self.synced_evidences.append(evidence)

    async def extract_session(
        self,
        session_id: str,
        evidences: Sequence[EvidenceRecord],
        scope: MemoryScopeContext,
    ) -> Sequence[DerivedObservationRecord]:
        return (
            DerivedObservationRecord(
                observation_id=f"{self._name}_extracted_1",
                scope=scope,
                content=f"Synthesized from {len(evidences)} turns",
                category="summary",
                status=MemoryLifecycleStage.PUBLISH,
                supporting_evidence_ids=tuple(e.evidence_id for e in evidences),
                proof_count=len(evidences),
                confidence=0.95,
                freshness=_utc_now(),
            ),
        )

    async def mirror_write(
        self,
        records: Sequence[DerivedObservationRecord],
    ) -> None:
        self.mirrored_records.extend(records)

    async def shutdown(self) -> None:
        pass


def test_is_trivial_prompt_filter() -> None:
    """Verify trivial prompts are identified to bypass wasteful retrieval roundtrips."""
    assert is_trivial_prompt("ok") is True
    assert is_trivial_prompt("thanks!") is True
    assert is_trivial_prompt("hello") is True
    assert is_trivial_prompt("lgtm") is True
    assert is_trivial_prompt("/reset") is True
    assert is_trivial_prompt("") is True
    assert is_trivial_prompt("How should we refactor the payment retry policy?") is False


@pytest.mark.asyncio
async def test_single_active_provider_activation_and_lifecycle() -> None:
    """Verify single active provider registration, activation, and 5-stage lifecycle."""
    mgr = SupersedesLineageManager()
    scheduler = SingleActiveProviderScheduler(lineage_manager=mgr, default_timeout_ms=300)

    p1 = MockExternalProvider(name="hindsight", kind=ProviderKind.HINDSIGHT)
    p2 = MockExternalProvider(name="mem0", kind=ProviderKind.MEM0)

    scheduler.register_provider(p1)
    scheduler.register_provider(p2)

    scheduler.activate_provider("hindsight")
    assert scheduler.active_provider is not None
    assert scheduler.active_provider.name == "hindsight"

    scope = MemoryScopeContext(scope_type=MemoryScopeType.PROJECT, owner_id="alice", project_id="pay_svc")
    prefetch_res = await scheduler.run_prefetch("sess_1", "Optimize payment backoff", scope)
    assert len(prefetch_res.observations) == 1
    assert prefetch_res.provider_name == "hindsight"
    assert prefetch_res.is_fallback is False

    injected_str = scheduler.format_inject("sess_1")
    assert "<external_recalled_memory>" in injected_str
    assert "External insight for Optimize payment backoff" in injected_str

    ev = EvidenceRecord(
        evidence_id="ev_101",
        session_id="sess_1",
        turn_index=0,
        source_event_id="evt_01",
        content="User says: switch to exponential backoff",
        actor="user",
    )
    await scheduler.run_sync_turn(ev)
    assert len(p1.synced_evidences) == 1
    assert mgr.get_evidence("ev_101") is not None

    extracted = await scheduler.run_extract_session("sess_1", (ev,), scope)
    assert len(extracted) == 1
    assert mgr.get_observation("hindsight_extracted_1") is not None

    await scheduler.run_mirror_write(extracted)
    assert len(p1.mirrored_records) == 1


@pytest.mark.asyncio
async def test_scheduler_circuit_breaking_fallback() -> None:
    """Verify scheduler falls back smoothly to internal memory when provider times out."""
    mgr = SupersedesLineageManager()
    slow_p = MockExternalProvider(name="slow_provider", sleep_ms=600)
    scheduler = SingleActiveProviderScheduler(lineage_manager=mgr, default_timeout_ms=100)
    scheduler.register_provider(slow_p)
    scheduler.activate_provider("slow_provider")

    scope = MemoryScopeContext(scope_type=MemoryScopeType.PERSONAL, owner_id="bob")
    local_obs = DerivedObservationRecord(
        observation_id="local_cached_obs",
        scope=scope,
        content="Fallback local knowledge",
        category="general",
        status=MemoryLifecycleStage.PUBLISH,
        supporting_evidence_ids=(),
        proof_count=1,
        confidence=0.8,
        freshness=_utc_now(),
    )
    mgr.publish_observation(local_obs)

    res = await scheduler.run_prefetch("sess_slow", "Query something", scope, timeout_ms=50)
    assert res.is_fallback is True
    assert any(obs.observation_id == "local_cached_obs" for obs in res.observations)


def test_supersedes_lineage_and_rollback() -> None:
    """Verify explicit supersedes version chaining and rollback functionality."""
    mgr = SupersedesLineageManager()
    scope = MemoryScopeContext(scope_type=MemoryScopeType.PROJECT, owner_id="alice", project_id="db_svc")

    v1 = DerivedObservationRecord(
        observation_id="db_cfg_v1",
        scope=scope,
        content="PostgreSQL pool size: 20",
        category="config",
        status=MemoryLifecycleStage.PUBLISH,
        supporting_evidence_ids=("ev_cfg_1",),
        proof_count=1,
        confidence=0.9,
        freshness=_utc_now(),
    )
    mgr.publish_observation(v1)

    v2 = DerivedObservationRecord(
        observation_id="db_cfg_v2",
        scope=scope,
        content="PostgreSQL pool size: 50",
        category="config",
        status=MemoryLifecycleStage.PUBLISH,
        supporting_evidence_ids=("ev_cfg_2",),
        proof_count=2,
        confidence=0.95,
        freshness=_utc_now(),
    )
    mgr.supersede_observation("db_cfg_v1", v2, "Increased traffic requirement")

    chain = mgr.get_lineage_chain("db_cfg_v2")
    assert len(chain) == 2
    assert chain[0].observation_id == "db_cfg_v2"
    assert chain[1].observation_id == "db_cfg_v1"

    old_v1 = mgr.get_observation("db_cfg_v1")
    assert old_v1 is not None
    assert old_v1.status == MemoryLifecycleStage.SUPERSEDE
    assert old_v1.superseded_by == "db_cfg_v2"

    rolled_back = mgr.rollback_to_version("db_cfg_v2", "db_cfg_v1", "Reverting pool size")
    assert rolled_back.content == "PostgreSQL pool size: 20"
    chain_post_rb = mgr.get_lineage_chain(rolled_back.observation_id)
    assert len(chain_post_rb) == 3


def test_cascade_delete_cleans_links_and_indices() -> None:
    """Verify atomic cascade deletion purges observations, evidence references, and graph/vector indices."""
    mgr = SupersedesLineageManager()
    scope = MemoryScopeContext(scope_type=MemoryScopeType.PERSONAL, owner_id="alice")
    ev = EvidenceRecord(
        evidence_id="ev_cascade_01",
        session_id="sess_c",
        turn_index=0,
        source_event_id="turn_c",
        content="User stated temporary IP address",
        actor="user",
    )
    mgr.record_evidence(ev)

    obs = DerivedObservationRecord(
        observation_id="obs_cascade_01",
        scope=scope,
        content="Temporary IP: 192.168.1.100",
        category="network",
        status=MemoryLifecycleStage.PUBLISH,
        supporting_evidence_ids=(ev.evidence_id,),
        proof_count=1,
        confidence=0.9,
        freshness=_utc_now(),
    )
    mgr.publish_observation(obs)
    mgr.associate_external_indices(
        "obs_cascade_01",
        graph_edge_ids=("edge_ip_rel",),
        vector_ids=("vec_ip_doc",),
    )

    del_res = mgr.cascade_delete("obs_cascade_01")
    assert "obs_cascade_01" in del_res.deleted_observation_ids
    assert "ev_cascade_01" in del_res.unlinked_evidence_ids
    assert "graph:edge_ip_rel" in del_res.invalidated_cache_keys
    assert "vector:vec_ip_doc" in del_res.invalidated_cache_keys
    assert mgr.get_observation("obs_cascade_01") is None


@pytest.mark.asyncio
async def test_3d_benchmark_suite_execution() -> None:
    """Verify 3D evaluation benchmark covers recall accuracy, lifecycle integrity, and overhead bounds."""
    mgr = SupersedesLineageManager()
    scheduler = SingleActiveProviderScheduler(lineage_manager=mgr)
    suite = ExternalMemoryBenchmarkSuite(scheduler)

    report = await suite.run_full_benchmark()
    assert report.recall_accuracy.passed is True
    assert report.recall_accuracy.score == 1.0
    assert report.lifecycle_integrity.passed is True
    assert report.lifecycle_integrity.score == 1.0
    assert report.operational_overhead.passed is True
    assert report.overall_passed is True
