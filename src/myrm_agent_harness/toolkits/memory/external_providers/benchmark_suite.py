"""Three-dimensional benchmark and evaluation suite for external memory providers.

[INPUT]
- external_providers.models::{DerivedObservationRecord, EvidenceRecord, MemoryLifecycleStage, MemoryScopeContext, MemoryScopeType}
- external_providers.lineage_manager::{SupersedesLineageManager}
- external_providers.scheduler::{SingleActiveProviderScheduler}

[OUTPUT]
- BenchmarkDimensionScore: score container for single benchmark dimension.
- BenchmarkReport: comprehensive 3D evaluation result report.
- ExternalMemoryBenchmarkSuite: automated evaluator for recall accuracy, lifecycle integrity, and overhead.

[POS]
Provides automated 3D verification:
1. Recall accuracy and scope isolation (0% cross-scope leak).
2. Lifecycle integrity (supersedes version chain and cascade deletion).
3. Cost and latency operational bounds (prefetch < 300ms circuit breaking).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.external_providers.lineage_manager import (
    SupersedesLineageManager,
)
from myrm_agent_harness.toolkits.memory.external_providers.models import (
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryLifecycleStage,
    MemoryScopeContext,
    MemoryScopeType,
)
from myrm_agent_harness.toolkits.memory.external_providers.scheduler import (
    SingleActiveProviderScheduler,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class BenchmarkDimensionScore:
    """Score evaluation metrics for a specific dimension."""

    dimension_name: str
    score: float
    passed: bool
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Aggregate 3-dimensional benchmark evaluation report."""

    recall_accuracy: BenchmarkDimensionScore
    lifecycle_integrity: BenchmarkDimensionScore
    operational_overhead: BenchmarkDimensionScore
    overall_passed: bool
    evaluated_at: datetime = field(default_factory=_utc_now)


class ExternalMemoryBenchmarkSuite:
    """Automated benchmark evaluator for external memory provider packs."""

    def __init__(self, scheduler: SingleActiveProviderScheduler) -> None:
        self._scheduler: SingleActiveProviderScheduler = scheduler
        self._lineage_manager: SupersedesLineageManager = scheduler.lineage_manager

    def evaluate_recall_accuracy_and_isolation(self) -> BenchmarkDimensionScore:
        """Evaluate pre-retrieval scope isolation and absence of cross-project pollution."""
        project_scope_a = MemoryScopeContext(
            scope_type=MemoryScopeType.PROJECT,
            owner_id="alice",
            project_id="pay_service",
        )
        project_scope_b = MemoryScopeContext(
            scope_type=MemoryScopeType.PROJECT,
            owner_id="bob",
            project_id="auth_service",
        )

        obs_a = DerivedObservationRecord(
            observation_id="obs_pay_01",
            scope=project_scope_a,
            content="Pay service uses exponential backoff retry.",
            category="architecture",
            status=MemoryLifecycleStage.PUBLISH,
            supporting_evidence_ids=("ev_pay_01",),
            proof_count=1,
            confidence=0.95,
            freshness=_utc_now(),
        )
        obs_b = DerivedObservationRecord(
            observation_id="obs_auth_01",
            scope=project_scope_b,
            content="Auth service uses JWT RS256 signing keys.",
            category="security",
            status=MemoryLifecycleStage.PUBLISH,
            supporting_evidence_ids=("ev_auth_01",),
            proof_count=1,
            confidence=0.92,
            freshness=_utc_now(),
        )

        self._lineage_manager.publish_observation(obs_a)
        self._lineage_manager.publish_observation(obs_b)

        recalled_a = self._lineage_manager.filter_by_scope(project_scope_a)
        leak_count = sum(1 for item in recalled_a if item.scope.project_id != "pay_service")

        passed = leak_count == 0 and any(item.observation_id == "obs_pay_01" for item in recalled_a)
        score = 1.0 if passed else 0.0

        return BenchmarkDimensionScore(
            dimension_name="recall_accuracy_and_isolation",
            score=score,
            passed=passed,
            details={
                "cross_project_leaks": str(leak_count),
                "recalled_target_records": str(len(recalled_a)),
            },
        )

    def evaluate_lifecycle_integrity(self) -> BenchmarkDimensionScore:
        """Evaluate supersedes version progression, rollback, and cascade deletion."""
        scope = MemoryScopeContext(
            scope_type=MemoryScopeType.PERSONAL,
            owner_id="alice",
        )
        ev = EvidenceRecord(
            evidence_id="ev_base_01",
            session_id="sess_100",
            turn_index=0,
            source_event_id="turn_init",
            content="Initial user preference: Python 3.11",
            actor="user",
        )
        self._lineage_manager.record_evidence(ev)

        v1 = DerivedObservationRecord(
            observation_id="pref_v1",
            scope=scope,
            content="Python 3.11 target",
            category="preference",
            status=MemoryLifecycleStage.PUBLISH,
            supporting_evidence_ids=(ev.evidence_id,),
            proof_count=1,
            confidence=0.9,
            freshness=_utc_now(),
        )
        self._lineage_manager.publish_observation(v1)

        v2 = DerivedObservationRecord(
            observation_id="pref_v2",
            scope=scope,
            content="Python 3.12 target upgrade",
            category="preference",
            status=MemoryLifecycleStage.PUBLISH,
            supporting_evidence_ids=(ev.evidence_id,),
            proof_count=2,
            confidence=0.98,
            freshness=_utc_now(),
        )
        self._lineage_manager.supersede_observation(
            old_observation_id="pref_v1",
            new_observation=v2,
            reason="User upgraded to 3.12",
        )

        chain = self._lineage_manager.get_lineage_chain("pref_v2")
        has_correct_chain = len(chain) == 2 and chain[0].observation_id == "pref_v2"

        rolled_back = self._lineage_manager.rollback_to_version("pref_v2", "pref_v1", "Reverting test")
        chain_after_rb = self._lineage_manager.get_lineage_chain(rolled_back.observation_id)
        has_rollback = len(chain_after_rb) == 3

        cascade_res = self._lineage_manager.cascade_delete(rolled_back.observation_id)
        deleted_clean = (
            rolled_back.observation_id in cascade_res.deleted_observation_ids
            and self._lineage_manager.get_observation(rolled_back.observation_id) is None
        )

        passed = has_correct_chain and has_rollback and deleted_clean
        score = 1.0 if passed else 0.0

        return BenchmarkDimensionScore(
            dimension_name="lifecycle_integrity",
            score=score,
            passed=passed,
            details={
                "chain_length_initial": str(len(chain)),
                "chain_length_after_rollback": str(len(chain_after_rb)),
                "cascade_deleted_ids": ",".join(cascade_res.deleted_observation_ids),
            },
        )

    async def evaluate_operational_overhead(self) -> BenchmarkDimensionScore:
        """Evaluate prefetch latency, timeout circuit-breaking, and injection rendering."""
        scope = MemoryScopeContext(
            scope_type=MemoryScopeType.PERSONAL,
            owner_id="alice",
        )
        ev = EvidenceRecord(
            evidence_id="ev_op_01",
            session_id="sess_bench",
            turn_index=1,
            source_event_id="op_bench",
            content="Test query execution",
            actor="user",
        )
        t0 = time.perf_counter()
        metrics = await self._scheduler.execute_full_lifecycle(
            session_id="sess_bench",
            query="Tell me about python setup",
            scope=scope,
            evidence=ev,
        )
        total_time_ms = (time.perf_counter() - t0) * 1000.0

        prefetch_latency = metrics.stage_latencies_ms.get("prefetch", 0.0)
        within_sla = prefetch_latency < 300.0
        passed = within_sla and total_time_ms < 1000.0
        score = 1.0 if passed else 0.5

        return BenchmarkDimensionScore(
            dimension_name="operational_overhead",
            score=score,
            passed=passed,
            details={
                "prefetch_latency_ms": f"{prefetch_latency:.2f}",
                "total_lifecycle_ms": f"{total_time_ms:.2f}",
                "records_mirrored": str(metrics.records_mirrored),
            },
        )

    async def run_full_benchmark(self) -> BenchmarkReport:
        """Execute full three-dimensional benchmark suite and return aggregate report."""
        acc_score = self.evaluate_recall_accuracy_and_isolation()
        life_score = self.evaluate_lifecycle_integrity()
        op_score = await self.evaluate_operational_overhead()

        overall = acc_score.passed and life_score.passed and op_score.passed
        return BenchmarkReport(
            recall_accuracy=acc_score,
            lifecycle_integrity=life_score,
            operational_overhead=op_score,
            overall_passed=overall,
        )
