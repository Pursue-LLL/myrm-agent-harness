"""Zero-Context Replay Benchmark Harness for MemOps.

Implements the rigorous Zero-Context Replay evaluation protocol (inspired by Metis / arXiv:2607.26760
and LoCoMo benchmarks). Evaluates genuine memory retention, zero-leakage forgetting,
and atomic mutation consistency without replaying conversational history.

[INPUT]
- myrm_agent_harness.toolkits.memory.memops.models::* (POS: schemas, requests, metrics)
- myrm_agent_harness.toolkits.memory.memops.executor::MemOpsExecutor (POS: core memory operation engine)

[OUTPUT]
- ZeroContextMemOpsHarness: Benchmark runner calculating quantitative MemOps scores.

[POS]
Objective benchmark harness establishing industrial evaluation standards for Agent memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from myrm_agent_harness.toolkits.memory.memops.executor import MemOpsExecutor
from myrm_agent_harness.toolkits.memory.memops.models import (
    MemOpFact,
    MemOpRequest,
    MemOpsBenchmarkMetrics,
    MemOpStatus,
    MemOpType,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkEpisode:
    """A benchmark episode defining injection, mutation, and verification expectations."""

    initial_facts: list[MemOpFact]
    forget_requests: list[MemOpRequest]
    update_requests: list[MemOpRequest]
    expected_active_facts: dict[str, str]  # entity.attribute -> expected_value
    expected_forgotten_entities: list[str]  # entities that must have zero presence
    reflection_goal: str
    scope_id: str = "benchmark_eval"


class ZeroContextMemOpsHarness:
    """Executes step-level and trajectory-level zero-context replay evaluations."""

    def __init__(self, executor: MemOpsExecutor | None = None) -> None:
        self.executor = executor or MemOpsExecutor()

    async def run_episode(self, episode: BenchmarkEpisode) -> MemOpsBenchmarkMetrics:
        """Execute a full zero-context evaluation episode and compute metric scores."""
        scope_id = episode.scope_id

        # Phase 1: Ingestion (Remember initial facts)
        for fact in episode.initial_facts:
            req = MemOpRequest(op_type=MemOpType.REMEMBER, scope_id=scope_id, fact=fact)
            res = await self.executor.execute(req)
            if res.status != MemOpStatus.SUCCESS:
                logger.warning("Failed to remember fact %s: %s", fact.fact_id, res.message)

        # Phase 2: Mutation (Apply Forgets and Updates)
        for forget_req in episode.forget_requests:
            forget_req.scope_id = scope_id
            await self.executor.execute(forget_req)

        for update_req in episode.update_requests:
            update_req.scope_id = scope_id
            await self.executor.execute(update_req)

        # Phase 3: Zero-Context Evaluation (Strictly NO dialogue replay)
        active_recalled = await self.executor.recall_active_facts(scope_id=scope_id)
        recalled_map: dict[str, str] = {
            f"{f.entity}.{f.attribute}": f.value for f in active_recalled
        }

        # 1. Evaluate Remember Recall (Active facts that should remain)
        expected_active_count = len(episode.expected_active_facts)
        matched_active_count = 0
        for key, exp_val in episode.expected_active_facts.items():
            if recalled_map.get(key) == exp_val:
                matched_active_count += 1

        remember_recall = (
            round(matched_active_count / expected_active_count, 4)
            if expected_active_count > 0
            else 1.0
        )

        # 2. Evaluate Forget Zero-Leakage Rate (Forgotten entities must be 0)
        leakage_count = 0
        total_forgotten_checks = len(episode.expected_forgotten_entities)
        for entity in episode.expected_forgotten_entities:
            # Check if any active fact retains this entity
            if any(f.entity.lower() == entity.lower() for f in active_recalled):
                leakage_count += 1

        forget_leakage_rate = (
            round(leakage_count / total_forgotten_checks, 4)
            if total_forgotten_checks > 0
            else 0.0
        )

        # 3. Evaluate Update Consistency Rate
        update_success = 0
        total_updates = len(episode.update_requests)
        for u in episode.update_requests:
            target_key = f"{u.target_entity}.{u.target_attribute}"
            if recalled_map.get(target_key) == u.new_value:
                update_success += 1

        update_consistency_rate = (
            round(update_success / total_updates, 4) if total_updates > 0 else 1.0
        )

        # 4. Evaluate Reflect Synthesis
        reflect_req = MemOpRequest(
            op_type=MemOpType.REFLECT,
            scope_id=scope_id,
            reflection_goal=episode.reflection_goal,
        )
        reflect_res = await self.executor.execute(reflect_req)
        has_insights = len(reflect_res.reflection_synthesis) > 0
        reflect_synthesis_score = 1.0 if has_insights and reflect_res.status == MemOpStatus.SUCCESS else 0.0

        # Overall pass threshold: recall >= 0.95, leakage == 0.0, update >= 0.95, reflect >= 0.90
        passed = (
            remember_recall >= 0.95
            and forget_leakage_rate == 0.0
            and update_consistency_rate >= 0.95
            and reflect_synthesis_score >= 0.90
        )

        return MemOpsBenchmarkMetrics(
            total_episodes=1,
            remember_recall=remember_recall,
            forget_leakage_rate=forget_leakage_rate,
            update_consistency_rate=update_consistency_rate,
            reflect_synthesis_score=reflect_synthesis_score,
            passed=passed,
        )
