"""Unit tests and Zero-Context Replay benchmark tests for the MemOps engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.memops.benchmark import (
    BenchmarkEpisode,
    ZeroContextMemOpsHarness,
)
from myrm_agent_harness.toolkits.memory.memops.executor import MemOpsExecutor
from myrm_agent_harness.toolkits.memory.memops.models import (
    MemOpFact,
    MemOpRequest,
    MemOpStatus,
    MemOpType,
)


class TestMemOpsExecutor:
    @pytest.mark.asyncio
    async def test_remember_and_idempotent_reinforcement(self) -> None:
        executor = MemOpsExecutor()

        fact1 = MemOpFact(
            entity="tooling",
            attribute="package_manager",
            value="uv",
            statement="User prefers uv for Python dependencies",
            confidence=0.85,
            evidence="user said: use uv",
        )
        res1 = await executor.remember(
            MemOpRequest(op_type=MemOpType.REMEMBER, fact=fact1)
        )
        assert res1.status == MemOpStatus.SUCCESS
        assert len(res1.affected_fact_ids) == 1

        # Re-remembering the exact same fact reinforces confidence
        fact2 = MemOpFact(
            entity="tooling",
            attribute="package_manager",
            value="uv",
            statement="User prefers uv for Python dependencies",
            evidence="user reiterated: uv only",
        )
        res2 = await executor.remember(
            MemOpRequest(op_type=MemOpType.REMEMBER, fact=fact2)
        )
        assert res2.status == MemOpStatus.SUCCESS
        assert res2.fact is not None
        assert res2.fact.fact_id == fact1.fact_id
        assert res2.fact.confidence == pytest.approx(0.95)
        assert "uv only" in res2.fact.evidence

    @pytest.mark.asyncio
    async def test_remember_conflict_detection(self) -> None:
        executor = MemOpsExecutor()

        await executor.remember(
            MemOpRequest(
                op_type=MemOpType.REMEMBER,
                fact=MemOpFact(
                    entity="tooling",
                    attribute="linter",
                    value="ruff",
                    statement="Use ruff",
                ),
            )
        )

        # Proposing contradictory value without update triggers conflict
        res = await executor.remember(
            MemOpRequest(
                op_type=MemOpType.REMEMBER,
                fact=MemOpFact(
                    entity="tooling",
                    attribute="linter",
                    value="flake8",
                    statement="Use flake8",
                ),
            )
        )
        assert res.status == MemOpStatus.CONFLICT
        assert "Contradiction detected" in res.message

    @pytest.mark.asyncio
    async def test_forget_zero_leakage_tombstone_and_hard(self) -> None:
        executor = MemOpsExecutor()

        fact = MemOpFact(
            entity="secret",
            attribute="api_key",
            value="sk-12345",
            statement="Temp key is sk-12345",
        )
        await executor.remember(MemOpRequest(op_type=MemOpType.REMEMBER, fact=fact))

        # Ensure active before forget
        active_before = await executor.recall_active_facts(scope_id="default")
        assert len(active_before) == 1

        # Forget by target_id (tombstone mode)
        res_forget = await executor.forget(
            MemOpRequest(
                op_type=MemOpType.FORGET,
                target_id=fact.fact_id,
                reason="Token invalidated",
            )
        )
        assert res_forget.status == MemOpStatus.SUCCESS

        # Zero-leakage verification: must NEVER appear in active recall
        active_after = await executor.recall_active_facts(scope_id="default")
        assert len(active_after) == 0

        # Querying specific term also yields 0
        recalled = await executor.recall_active_facts(scope_id="default", query="sk-12345")
        assert len(recalled) == 0

    @pytest.mark.asyncio
    async def test_forget_by_entity_cascade(self) -> None:
        executor = MemOpsExecutor()

        await executor.remember(
            MemOpRequest(
                op_type=MemOpType.REMEMBER,
                fact=MemOpFact(
                    entity="legacy_service",
                    attribute="port",
                    value="9000",
                    statement="Port 9000",
                ),
            )
        )
        await executor.remember(
            MemOpRequest(
                op_type=MemOpType.REMEMBER,
                fact=MemOpFact(
                    entity="legacy_service",
                    attribute="host",
                    value="localhost",
                    statement="Host localhost",
                ),
            )
        )

        res = await executor.forget(
            MemOpRequest(
                op_type=MemOpType.FORGET,
                target_entity="legacy_service",
                hard_delete=True,
            )
        )
        assert res.status == MemOpStatus.SUCCESS
        assert len(res.affected_fact_ids) == 2

        active = await executor.recall_active_facts(scope_id="default")
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_update_versioned_state_mutation(self) -> None:
        executor = MemOpsExecutor()

        fact = MemOpFact(
            entity="runtime",
            attribute="python_version",
            value="3.11",
            statement="Environment uses Python 3.11",
        )
        await executor.remember(MemOpRequest(op_type=MemOpType.REMEMBER, fact=fact))

        res_update = await executor.update(
            MemOpRequest(
                op_type=MemOpType.UPDATE,
                target_id=fact.fact_id,
                new_value="3.12",
                new_statement="Environment upgraded to Python 3.12",
                new_evidence="pyproject.toml requires-python updated to >=3.12",
            )
        )
        assert res_update.status == MemOpStatus.SUCCESS
        assert res_update.fact is not None
        assert res_update.fact.value == "3.12"
        assert res_update.fact.version == 2
        assert "3.12" in res_update.fact.statement

    @pytest.mark.asyncio
    async def test_reflect_inductive_synthesis(self) -> None:
        executor = MemOpsExecutor()

        await executor.remember(
            MemOpRequest(
                op_type=MemOpType.REMEMBER,
                fact=MemOpFact(
                    entity="db_cluster",
                    attribute="engine",
                    value="postgres",
                    statement="Database engine is postgres",
                ),
            )
        )
        await executor.remember(
            MemOpRequest(
                op_type=MemOpType.REMEMBER,
                fact=MemOpFact(
                    entity="db_cluster",
                    attribute="pool_size",
                    value="20",
                    statement="Connection pool size is 20",
                ),
            )
        )

        res = await executor.reflect(
            MemOpRequest(
                op_type=MemOpType.REFLECT,
                reflection_goal="database configuration",
            )
        )
        assert res.status == MemOpStatus.SUCCESS
        assert len(res.reflection_synthesis) >= 1
        assert any("db_cluster" in s for s in res.reflection_synthesis)


class TestZeroContextMemOpsBenchmark:
    @pytest.mark.asyncio
    async def test_zero_context_replay_episode_evaluation(self, tmp_path: Path) -> None:
        storage_dir = tmp_path / "memops_store"
        executor = MemOpsExecutor(storage_dir=storage_dir)
        harness = ZeroContextMemOpsHarness(executor=executor)

        # Construct realistic episode: Ingest 3 facts -> Forget 1 -> Update 1 -> Verify
        fact_preserve = MemOpFact(
            entity="auth",
            attribute="scheme",
            value="bearer",
            statement="Auth scheme is bearer token",
        )
        fact_to_forget = MemOpFact(
            entity="temporary_cache",
            attribute="endpoint",
            value="redis://localhost:6379",
            statement="Redis is at localhost:6379",
        )
        fact_to_update = MemOpFact(
            entity="service",
            attribute="port",
            value="8000",
            statement="Service port is 8000",
        )

        episode = BenchmarkEpisode(
            initial_facts=[fact_preserve, fact_to_forget, fact_to_update],
            forget_requests=[
                MemOpRequest(
                    op_type=MemOpType.FORGET,
                    target_id=fact_to_forget.fact_id,
                    reason="Deprecated local cache",
                )
            ],
            update_requests=[
                MemOpRequest(
                    op_type=MemOpType.UPDATE,
                    target_entity="service",
                    target_attribute="port",
                    new_value="8080",
                    new_statement="Service port is 8080",
                )
            ],
            expected_active_facts={
                "auth.scheme": "bearer",
                "service.port": "8080",
            },
            expected_forgotten_entities=["temporary_cache"],
            reflection_goal="service connectivity and auth",
        )

        metrics = await harness.run_episode(episode)

        assert metrics.total_episodes == 1
        assert metrics.remember_recall == 1.0
        assert metrics.forget_leakage_rate == 0.0
        assert metrics.update_consistency_rate == 1.0
        assert metrics.reflect_synthesis_score == 1.0
        assert metrics.passed is True
