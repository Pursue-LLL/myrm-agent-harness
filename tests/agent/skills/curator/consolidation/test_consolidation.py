"""Tests for the skill consolidation subsystem."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.curator.consolidation.cluster_detector import ClusterDetector
from myrm_agent_harness.agent.skills.curator.consolidation.executor import ConsolidationExecutor
from myrm_agent_harness.agent.skills.curator.consolidation.judge import ConsolidationJudge
from myrm_agent_harness.agent.skills.curator.consolidation.orchestrator import SkillConsolidator
from myrm_agent_harness.agent.skills.curator.consolidation.types import (
    ConsolidationAction,
    ConsolidationActionType,
    ConsolidationPlan,
    ConsolidationReport,
    ConsolidationResult,
    SkillCluster,
)
from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillUsageStats,
)


def _make_skill(
    name: str,
    description: str = "Test skill",
    *,
    pinned: bool = False,
    status: str = SkillLifecycleStatus.ACTIVE,
    call_count: int = 5,
    storage_path: str | None = None,
) -> SkillMetadata:
    """Create a mock SkillMetadata for testing."""
    return SkillMetadata(
        name=name,
        description=description,
        storage_path=storage_path or f"/tmp/skills/{name}",
        usage_stats=SkillUsageStats(
            call_count=call_count,
            success_count=call_count,
            lifecycle_status=status,
            pinned=pinned,
            last_used_at=datetime.now(UTC) - timedelta(days=5),
            created_at=datetime.now(UTC) - timedelta(days=30),
        ),
    )


class TestSkillCluster:
    """Tests for SkillCluster data type."""

    def test_cluster_creation(self) -> None:
        cluster = SkillCluster(
            cluster_id="test-1",
            skill_names=("git_commit_skill", "git_push_skill", "git_merge_skill"),
            shared_domain="git",
            avg_similarity=0.85,
            representative_keywords=("git", "commit", "push"),
        )
        assert cluster.cluster_id == "test-1"
        assert len(cluster.skill_names) == 3
        assert cluster.avg_similarity == 0.85

    def test_cluster_immutable(self) -> None:
        cluster = SkillCluster(
            cluster_id="test-1",
            skill_names=("a", "b", "c"),
            shared_domain="test",
            avg_similarity=0.8,
        )
        with pytest.raises(AttributeError):
            cluster.cluster_id = "changed"  # type: ignore[misc]


class TestConsolidationPlan:
    """Tests for ConsolidationPlan data type."""

    def test_empty_plan(self) -> None:
        plan = ConsolidationPlan()
        assert plan.is_empty
        assert plan.merge_count == 0
        assert plan.create_count == 0
        assert plan.demote_count == 0

    def test_plan_with_actions(self) -> None:
        actions = [
            ConsolidationAction(
                action_type=ConsolidationActionType.MERGE,
                target_skill="git_operations_skill",
                source_skills=("git_commit_skill", "git_push_skill"),
                reasoning="Related git operations",
            ),
            ConsolidationAction(
                action_type=ConsolidationActionType.CREATE_UMBRELLA,
                target_skill="deploy_skill",
                source_skills=("deploy_docker_skill", "deploy_k8s_skill", "deploy_ec2_skill"),
                reasoning="All deployment related",
                umbrella_description="Unified deployment operations",
            ),
        ]
        plan = ConsolidationPlan(
            actions=actions,
            total_skills_affected=5,
            estimated_reduction=3,
        )
        assert not plan.is_empty
        assert plan.merge_count == 1
        assert plan.create_count == 1
        assert plan.demote_count == 0
        assert plan.estimated_reduction == 3


class TestConsolidationReport:
    """Tests for ConsolidationReport."""

    def test_empty_report(self) -> None:
        report = ConsolidationReport()
        assert report.net_reduction == 0
        assert report.success_count == 0
        assert report.failure_count == 0
        assert "No consolidation" in report.to_summary()

    def test_report_with_results(self) -> None:
        action = ConsolidationAction(
            action_type=ConsolidationActionType.MERGE,
            target_skill="umbrella",
            source_skills=("a", "b"),
            reasoning="test",
        )
        report = ConsolidationReport(
            results=[
                ConsolidationResult(action=action, success=True, archived_skills=("a", "b")),
            ],
            skills_before=10,
            skills_after=8,
            total_archived=2,
        )
        assert report.net_reduction == 2
        assert report.success_count == 1
        assert report.failure_count == 0


class TestClusterDetector:
    """Tests for ClusterDetector prefix-based detection."""

    @pytest.fixture
    def mock_embedding_service(self) -> MagicMock:
        service = MagicMock()
        service.embed_batch = AsyncMock(return_value=[[0.1] * 128] * 5)
        service.embed = AsyncMock(return_value=[0.1] * 128)
        return service

    def test_prefix_clustering(self, mock_embedding_service: MagicMock) -> None:
        detector = ClusterDetector(mock_embedding_service, min_cluster_size=3)
        skills = [
            _make_skill("git_commit_skill", "Commit changes to git"),
            _make_skill("git_push_skill", "Push changes to remote"),
            _make_skill("git_merge_skill", "Merge branches"),
            _make_skill("deploy_docker_skill", "Deploy with Docker"),
            _make_skill("deploy_k8s_skill", "Deploy to Kubernetes"),
        ]

        clusters = detector._detect_prefix_clusters(skills)
        git_clusters = [c for c in clusters if "git" in c.shared_domain]
        assert len(git_clusters) == 1
        assert len(git_clusters[0].skill_names) == 3

    @pytest.mark.asyncio
    async def test_detect_returns_clusters(self, mock_embedding_service: MagicMock) -> None:
        import numpy as np

        high_sim_vectors = np.random.default_rng(42).random((5, 128))
        high_sim_vectors[:3] = high_sim_vectors[0] + np.random.default_rng(42).random((3, 128)) * 0.05

        mock_embedding_service.embed_batch = AsyncMock(return_value=high_sim_vectors.tolist())

        detector = ClusterDetector(
            mock_embedding_service,
            min_cluster_size=3,
            similarity_threshold=0.95,
        )
        skills = [
            _make_skill(f"skill_{i}", f"Description {i}")
            for i in range(5)
        ]

        clusters = await detector.detect(skills)
        assert isinstance(clusters, list)

    @pytest.mark.asyncio
    async def test_detect_too_few_skills(self, mock_embedding_service: MagicMock) -> None:
        detector = ClusterDetector(mock_embedding_service, min_cluster_size=3)
        skills = [_make_skill("only_one_skill")]
        clusters = await detector.detect(skills)
        assert clusters == []


class TestConsolidationJudge:
    """Tests for ConsolidationJudge LLM interaction."""

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        llm = MagicMock()
        return llm

    @pytest.mark.asyncio
    async def test_judge_keep_decision(self, mock_llm: MagicMock) -> None:
        from myrm_agent_harness.agent.skills.curator.consolidation.judge import _ClusterJudgment

        mock_structured = AsyncMock(return_value=_ClusterJudgment(
            action="keep",
            target_skill_name="any",
            reasoning="Skills serve distinct purposes",
        ))
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        judge = ConsolidationJudge(mock_llm)
        cluster = SkillCluster(
            cluster_id="test-cluster",
            skill_names=("a_skill", "b_skill", "c_skill"),
            shared_domain="testing",
            avg_similarity=0.76,
        )

        plan = await judge.judge_clusters([cluster], [])
        assert plan.is_empty

    @pytest.mark.asyncio
    async def test_judge_merge_decision(self, mock_llm: MagicMock) -> None:
        from myrm_agent_harness.agent.skills.curator.consolidation.judge import _ClusterJudgment

        mock_structured = AsyncMock(return_value=_ClusterJudgment(
            action="merge",
            target_skill_name="git_operations_skill",
            reasoning="git_operations_skill is already broad enough",
        ))
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        judge = ConsolidationJudge(mock_llm)
        skills = [
            _make_skill("git_operations_skill", "Git operations"),
            _make_skill("git_commit_skill", "Commit changes"),
            _make_skill("git_push_skill", "Push changes"),
        ]
        cluster = SkillCluster(
            cluster_id="prefix-git",
            skill_names=("git_operations_skill", "git_commit_skill", "git_push_skill"),
            shared_domain="git",
            avg_similarity=0.85,
        )

        plan = await judge.judge_clusters([cluster], skills)
        assert not plan.is_empty
        assert plan.actions[0].action_type == ConsolidationActionType.MERGE
        assert plan.actions[0].target_skill == "git_operations_skill"
        assert "git_commit_skill" in plan.actions[0].source_skills


class TestConsolidationExecutor:
    """Tests for ConsolidationExecutor."""

    @pytest.fixture
    def mock_write_backend(self) -> MagicMock:
        backend = MagicMock()
        backend.save_skill = AsyncMock(return_value=MagicMock(
            success=True,
            saved_path="/tmp/skills/umbrella_skill",
            error="",
        ))
        backend.write_resource = AsyncMock(return_value=MagicMock(success=True))
        return backend

    @pytest.fixture
    def stats_collector(self, tmp_path: Path) -> MagicMock:
        collector = MagicMock()
        collector.get_stats = MagicMock(return_value=SkillUsageStats(
            call_count=0, success_count=0, created_at=datetime.now(UTC),
        ))
        collector.update_lifecycle_status = MagicMock()
        collector.flush = MagicMock()
        return collector

    @pytest.mark.asyncio
    async def test_execute_create_umbrella(
        self, mock_write_backend: MagicMock, stats_collector: MagicMock
    ) -> None:
        skills = [
            _make_skill("git_commit_skill", "Commit changes"),
            _make_skill("git_push_skill", "Push changes"),
            _make_skill("git_merge_skill", "Merge branches"),
        ]
        action = ConsolidationAction(
            action_type=ConsolidationActionType.CREATE_UMBRELLA,
            target_skill="git_operations_skill",
            source_skills=("git_commit_skill", "git_push_skill", "git_merge_skill"),
            reasoning="Create umbrella for git ops",
            umbrella_description="Unified git operations",
            umbrella_content_outline="Covers commit, push, merge operations.",
        )

        executor = ConsolidationExecutor(mock_write_backend, stats_collector, skills)
        report = await executor.execute([action])

        assert report.success_count == 1
        assert report.failure_count == 0
        assert report.total_created == 1
        mock_write_backend.save_skill.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_merge(
        self, mock_write_backend: MagicMock, stats_collector: MagicMock
    ) -> None:
        skills = [
            _make_skill("git_operations_skill", "Git operations"),
            _make_skill("git_commit_skill", "Commit changes"),
        ]
        action = ConsolidationAction(
            action_type=ConsolidationActionType.MERGE,
            target_skill="git_operations_skill",
            source_skills=("git_commit_skill",),
            reasoning="Merge into existing",
        )

        executor = ConsolidationExecutor(mock_write_backend, stats_collector, skills)
        report = await executor.execute([action])

        assert report.success_count == 1
        mock_write_backend.write_resource.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_missing_target(
        self, mock_write_backend: MagicMock, stats_collector: MagicMock
    ) -> None:
        skills = [_make_skill("only_skill", "Only skill")]
        action = ConsolidationAction(
            action_type=ConsolidationActionType.MERGE,
            target_skill="nonexistent_skill",
            source_skills=("only_skill",),
            reasoning="test",
        )

        executor = ConsolidationExecutor(mock_write_backend, stats_collector, skills)
        report = await executor.execute([action])

        assert report.failure_count == 1
        assert "not found" in report.results[0].error


class TestSkillConsolidatorOrchestrator:
    """Tests for the top-level SkillConsolidator."""

    @pytest.fixture
    def mock_deps(self) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
        embedding_service = MagicMock()
        embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 128] * 3)
        llm = MagicMock()
        write_backend = MagicMock()
        stats_collector = MagicMock()
        return embedding_service, llm, write_backend, stats_collector

    @pytest.mark.asyncio
    async def test_run_too_few_skills(
        self, mock_deps: tuple[MagicMock, MagicMock, MagicMock, MagicMock]
    ) -> None:
        embed, llm, write, stats = mock_deps
        consolidator = SkillConsolidator(
            embed, llm, write, stats, min_skills_for_consolidation=10
        )
        skills = [_make_skill(f"skill_{i}") for i in range(5)]
        result = await consolidator.run(skills, dry_run=True)
        assert isinstance(result, ConsolidationPlan)
        assert result.is_empty

    def test_filter_eligible_excludes_pinned(self) -> None:
        skills = [
            _make_skill("normal_skill"),
            _make_skill("pinned_skill", pinned=True),
            _make_skill("archived_skill", status=SkillLifecycleStatus.ARCHIVED),
        ]
        eligible = SkillConsolidator._filter_eligible(skills)
        assert len(eligible) == 1
        assert eligible[0].name == "normal_skill"

    def test_filter_eligible_excludes_mcp(self) -> None:
        mcp_skill = _make_skill("mcp_skill", storage_path=None)
        mcp_skill.storage_path = None
        skills = [_make_skill("normal"), mcp_skill]
        eligible = SkillConsolidator._filter_eligible(skills)
        names = [s.name for s in eligible]
        assert "mcp_skill" not in names


class TestConsolidationExecutorDemote:
    """Tests for ConsolidationExecutor DEMOTE action."""

    @pytest.fixture
    def mock_write_backend(self) -> MagicMock:
        backend = MagicMock()
        backend.write_resource = AsyncMock(return_value=MagicMock(success=True))
        return backend

    @pytest.fixture
    def stats_collector(self) -> MagicMock:
        collector = MagicMock()
        collector.get_stats = MagicMock(return_value=SkillUsageStats(
            call_count=0, success_count=0, created_at=datetime.now(UTC),
        ))
        collector.update_lifecycle_status = MagicMock()
        collector.flush = MagicMock()
        return collector

    @pytest.mark.asyncio
    async def test_execute_demote_success(
        self, mock_write_backend: MagicMock, stats_collector: MagicMock
    ) -> None:
        skills = [
            _make_skill("main_skill", "Main skill"),
            _make_skill("narrow_a", "Narrow helper A"),
            _make_skill("narrow_b", "Narrow helper B"),
        ]
        action = ConsolidationAction(
            action_type=ConsolidationActionType.DEMOTE,
            target_skill="main_skill",
            source_skills=("narrow_a", "narrow_b"),
            reasoning="Narrow skills should be support files",
            demote_target_dir="references",
        )

        executor = ConsolidationExecutor(mock_write_backend, stats_collector, skills)
        report = await executor.execute([action])

        assert report.success_count == 1
        assert report.failure_count == 0
        assert mock_write_backend.write_resource.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_demote_no_sources(
        self, mock_write_backend: MagicMock, stats_collector: MagicMock
    ) -> None:
        skills = [_make_skill("main_skill")]
        action = ConsolidationAction(
            action_type=ConsolidationActionType.DEMOTE,
            target_skill="main_skill",
            source_skills=("nonexistent_a", "nonexistent_b"),
            reasoning="test",
        )

        executor = ConsolidationExecutor(mock_write_backend, stats_collector, skills)
        report = await executor.execute([action])

        assert report.failure_count == 1
        assert "No source" in report.results[0].error


class TestConsolidationExecutorKeep:
    """Tests for ConsolidationExecutor KEEP action."""

    @pytest.mark.asyncio
    async def test_execute_keep(self) -> None:
        action = ConsolidationAction(
            action_type=ConsolidationActionType.KEEP,
            target_skill="any_skill",
            source_skills=("a", "b"),
            reasoning="No action needed",
        )
        backend = MagicMock()
        stats = MagicMock()
        executor = ConsolidationExecutor(backend, stats, [])
        report = await executor.execute([action])

        assert report.success_count == 1
        assert report.failure_count == 0


class TestConsolidationExecutorExceptionHandling:
    """Tests for executor error handling paths."""

    @pytest.mark.asyncio
    async def test_execute_action_raises_exception(self) -> None:
        backend = MagicMock()
        backend.save_skill = AsyncMock(side_effect=RuntimeError("Write failed"))
        stats = MagicMock()
        stats.get_stats = MagicMock(return_value=SkillUsageStats(
            call_count=0, success_count=0, created_at=datetime.now(UTC),
        ))

        skills = [_make_skill("src_skill")]
        action = ConsolidationAction(
            action_type=ConsolidationActionType.CREATE_UMBRELLA,
            target_skill="new_umbrella",
            source_skills=("src_skill",),
            reasoning="test exception",
            umbrella_description="test",
        )

        executor = ConsolidationExecutor(backend, stats, skills)
        report = await executor.execute([action])

        assert report.failure_count == 1
        assert "Write failed" in report.results[0].error


class TestSkillConsolidatorFullPipeline:
    """Tests for orchestrator full execution path (non-dry-run)."""

    @pytest.mark.asyncio
    async def test_run_dry_run_with_detected_clusters(self) -> None:
        """Full pipeline: enough skills, clusters detected, plan returned."""
        from myrm_agent_harness.agent.skills.curator.consolidation.judge import _ClusterJudgment

        mock_embed = MagicMock()
        mock_embed.embed_batch = AsyncMock(return_value=[[0.1] * 128] * 12)

        mock_structured = AsyncMock(return_value=_ClusterJudgment(
            action="create_umbrella",
            target_skill_name="git_operations_skill",
            reasoning="Create umbrella for git domain",
            umbrella_description="Git operations umbrella",
            umbrella_content_outline="Covers all git operations.",
        ))
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        mock_write = MagicMock()
        mock_stats = MagicMock()

        consolidator = SkillConsolidator(
            mock_embed, mock_llm, mock_write, mock_stats,
            min_skills_for_consolidation=3,
            min_cluster_size=3,
            similarity_threshold=0.95,
        )

        skills = [
            _make_skill("git_commit_skill", "Commit changes"),
            _make_skill("git_push_skill", "Push to remote"),
            _make_skill("git_merge_skill", "Merge branches"),
            _make_skill("deploy_skill", "Deploy app"),
        ]

        result = await consolidator.run(skills, dry_run=True)
        assert isinstance(result, ConsolidationPlan)
        assert not result.is_empty
        assert result.actions[0].action_type == ConsolidationActionType.CREATE_UMBRELLA

    @pytest.mark.asyncio
    async def test_run_execute_mode(self) -> None:
        """Full pipeline execute mode: creates umbrella, archives sources."""
        from myrm_agent_harness.agent.skills.curator.consolidation.judge import _ClusterJudgment

        mock_embed = MagicMock()
        mock_embed.embed_batch = AsyncMock(return_value=[[0.1] * 128] * 12)

        mock_structured = AsyncMock(return_value=_ClusterJudgment(
            action="merge",
            target_skill_name="git_commit_skill",
            reasoning="Merge into existing broader skill",
        ))
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        mock_write = MagicMock()
        mock_write.write_resource = AsyncMock(return_value=MagicMock(success=True))
        mock_stats = MagicMock()
        mock_stats.get_stats = MagicMock(return_value=SkillUsageStats(
            call_count=0, success_count=0, created_at=datetime.now(UTC),
        ))
        mock_stats.update_lifecycle_status = MagicMock()
        mock_stats.flush = MagicMock()

        consolidator = SkillConsolidator(
            mock_embed, mock_llm, mock_write, mock_stats,
            min_skills_for_consolidation=3,
            min_cluster_size=3,
            similarity_threshold=0.95,
        )

        skills = [
            _make_skill("git_commit_skill", "Commit changes"),
            _make_skill("git_push_skill", "Push to remote"),
            _make_skill("git_merge_skill", "Merge branches"),
            _make_skill("deploy_skill", "Deploy app"),
        ]

        result = await consolidator.run(skills, dry_run=False)
        assert isinstance(result, ConsolidationReport)
        assert result.success_count >= 1

    @pytest.mark.asyncio
    async def test_run_no_clusters_detected(self) -> None:
        """Pipeline with enough skills but no clusters found."""
        mock_embed = MagicMock()
        mock_embed.embed_batch = AsyncMock(return_value=[[0.0] * 128] * 5)

        mock_llm = MagicMock()
        mock_write = MagicMock()
        mock_stats = MagicMock()

        consolidator = SkillConsolidator(
            mock_embed, mock_llm, mock_write, mock_stats,
            min_skills_for_consolidation=3,
            min_cluster_size=3,
            similarity_threshold=0.99,
        )

        skills = [
            _make_skill(f"unique_{i}", f"Completely unique description {i}")
            for i in range(5)
        ]

        result = await consolidator.run(skills, dry_run=True)
        assert isinstance(result, ConsolidationPlan)
        assert result.is_empty

    @pytest.mark.asyncio
    async def test_run_judge_returns_keep_for_all(self) -> None:
        """Pipeline where judge decides KEEP for all clusters."""
        from myrm_agent_harness.agent.skills.curator.consolidation.judge import _ClusterJudgment

        mock_embed = MagicMock()
        mock_embed.embed_batch = AsyncMock(return_value=[[0.1] * 128] * 12)

        mock_structured = AsyncMock(return_value=_ClusterJudgment(
            action="keep",
            target_skill_name="any",
            reasoning="Skills serve distinct purposes",
        ))
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        mock_write = MagicMock()
        mock_stats = MagicMock()

        consolidator = SkillConsolidator(
            mock_embed, mock_llm, mock_write, mock_stats,
            min_skills_for_consolidation=3,
            min_cluster_size=3,
            similarity_threshold=0.95,
        )

        skills = [
            _make_skill("git_commit_skill", "Commit"),
            _make_skill("git_push_skill", "Push"),
            _make_skill("git_merge_skill", "Merge"),
            _make_skill("deploy_skill", "Deploy"),
        ]

        result = await consolidator.run(skills, dry_run=True)
        assert isinstance(result, ConsolidationPlan)
        assert result.is_empty


class TestConsolidationJudgeEdgeCases:
    """Edge cases for the consolidation judge."""

    @pytest.mark.asyncio
    async def test_judge_llm_returns_none(self) -> None:
        """LLM returns None — should result in empty plan."""
        mock_structured = AsyncMock(return_value=None)
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        judge = ConsolidationJudge(mock_llm)
        cluster = SkillCluster(
            cluster_id="test",
            skill_names=("a", "b", "c"),
            shared_domain="test",
            avg_similarity=0.8,
        )

        plan = await judge.judge_clusters([cluster], [])
        assert plan.is_empty

    @pytest.mark.asyncio
    async def test_judge_llm_raises_exception(self) -> None:
        """LLM raises exception — should be caught, empty plan."""
        mock_structured = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        judge = ConsolidationJudge(mock_llm)
        cluster = SkillCluster(
            cluster_id="test",
            skill_names=("x", "y", "z"),
            shared_domain="test",
            avg_similarity=0.9,
        )

        plan = await judge.judge_clusters([cluster], [])
        assert plan.is_empty

    @pytest.mark.asyncio
    async def test_judge_create_umbrella_decision(self) -> None:
        """LLM decides create_umbrella — should produce correct action."""
        from myrm_agent_harness.agent.skills.curator.consolidation.judge import _ClusterJudgment

        mock_structured = AsyncMock(return_value=_ClusterJudgment(
            action="create_umbrella",
            target_skill_name="deploy_operations_skill",
            reasoning="No single skill covers all deployment",
            umbrella_description="Unified deployment operations",
            umbrella_content_outline="Docker, K8s, and EC2 deployments",
        ))
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        judge = ConsolidationJudge(mock_llm)
        skills = [
            _make_skill("deploy_docker_skill", "Deploy with Docker"),
            _make_skill("deploy_k8s_skill", "Deploy to Kubernetes"),
            _make_skill("deploy_ec2_skill", "Deploy to EC2"),
        ]
        cluster = SkillCluster(
            cluster_id="prefix-deploy",
            skill_names=("deploy_docker_skill", "deploy_k8s_skill", "deploy_ec2_skill"),
            shared_domain="deploy",
            avg_similarity=0.88,
        )

        plan = await judge.judge_clusters([cluster], skills)
        assert not plan.is_empty
        assert plan.actions[0].action_type == ConsolidationActionType.CREATE_UMBRELLA
        assert plan.actions[0].umbrella_description == "Unified deployment operations"

    @pytest.mark.asyncio
    async def test_judge_demote_decision(self) -> None:
        """LLM decides demote — should produce correct action with target dir."""
        from myrm_agent_harness.agent.skills.curator.consolidation.judge import _ClusterJudgment

        mock_structured = AsyncMock(return_value=_ClusterJudgment(
            action="demote",
            target_skill_name="main_skill",
            reasoning="Helper skills are too narrow",
            demote_target_dir="scripts",
        ))
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=mock_structured))

        judge = ConsolidationJudge(mock_llm)
        skills = [
            _make_skill("main_skill", "Main skill"),
            _make_skill("helper_a", "Helper A"),
            _make_skill("helper_b", "Helper B"),
        ]
        cluster = SkillCluster(
            cluster_id="test-demote",
            skill_names=("main_skill", "helper_a", "helper_b"),
            shared_domain="helpers",
            avg_similarity=0.75,
        )

        plan = await judge.judge_clusters([cluster], skills)
        assert not plan.is_empty
        assert plan.actions[0].action_type == ConsolidationActionType.DEMOTE
        assert plan.actions[0].demote_target_dir == "scripts"


class TestClusterDetectorEdgeCases:
    """Edge case tests for ClusterDetector."""

    def test_extract_prefix_single_word(self) -> None:
        prefix = ClusterDetector._extract_prefix("singleword")
        assert prefix == ""

    def test_extract_prefix_multi_word(self) -> None:
        prefix = ClusterDetector._extract_prefix("git-commit-fast")
        assert prefix == "git"

    def test_deduplicate_clusters_overlap(self) -> None:
        mock_embed = MagicMock()
        detector = ClusterDetector(mock_embed, min_cluster_size=3)

        prefix_clusters = [
            SkillCluster(
                cluster_id="prefix-git",
                skill_names=("git_a", "git_b", "git_c"),
                shared_domain="git",
                avg_similarity=1.0,
            )
        ]
        embedding_clusters = [
            SkillCluster(
                cluster_id="semantic-git",
                skill_names=("git_a", "git_b", "git_c"),
                shared_domain="git",
                avg_similarity=0.9,
            )
        ]

        merged = detector._deduplicate_clusters(prefix_clusters, embedding_clusters)
        assert len(merged) == 1

    def test_deduplicate_clusters_no_overlap(self) -> None:
        mock_embed = MagicMock()
        detector = ClusterDetector(mock_embed, min_cluster_size=3)

        prefix_clusters = [
            SkillCluster(
                cluster_id="prefix-git",
                skill_names=("git_a", "git_b", "git_c"),
                shared_domain="git",
                avg_similarity=1.0,
            )
        ]
        embedding_clusters = [
            SkillCluster(
                cluster_id="semantic-deploy",
                skill_names=("deploy_a", "deploy_b", "deploy_c"),
                shared_domain="deploy",
                avg_similarity=0.85,
            )
        ]

        merged = detector._deduplicate_clusters(prefix_clusters, embedding_clusters)
        assert len(merged) == 2


class TestConsolidationReportSummary:
    """Tests for ConsolidationReport.to_summary output."""

    def test_summary_with_failures(self) -> None:
        action_ok = ConsolidationAction(
            action_type=ConsolidationActionType.MERGE,
            target_skill="t",
            source_skills=("a",),
            reasoning="test",
        )
        action_fail = ConsolidationAction(
            action_type=ConsolidationActionType.CREATE_UMBRELLA,
            target_skill="u",
            source_skills=("b",),
            reasoning="test",
        )
        report = ConsolidationReport(
            results=[
                ConsolidationResult(action=action_ok, success=True, archived_skills=("a",)),
                ConsolidationResult(action=action_fail, success=False, error="disk full"),
            ],
            skills_before=10,
            skills_after=9,
            total_archived=1,
        )
        summary = report.to_summary()
        assert "failed" in summary.lower()
        assert "10" in summary
        assert "9" in summary


class TestCuratorEngineConsolidationIntegration:
    """Tests for SkillCurator async consolidation integration."""

    @pytest.mark.asyncio
    async def test_run_async_without_consolidation(self, tmp_path: Path) -> None:
        from myrm_agent_harness.agent.skills.curator.engine import SkillCurator
        from myrm_agent_harness.backends.skills.forgetting_strategy import CuratorConfig
        from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        config = CuratorConfig(enabled=True, consolidation_enabled=False)
        collector = SkillStatsCollector(skills_dir)
        curator = SkillCurator(collector, config)

        assert not curator.consolidation_available
        _result, consolidation = await curator.run_async([])
        assert consolidation is None

    @pytest.mark.asyncio
    async def test_run_async_with_consolidation_deps(self, tmp_path: Path) -> None:
        from myrm_agent_harness.agent.skills.curator.engine import SkillCurator
        from myrm_agent_harness.backends.skills.forgetting_strategy import CuratorConfig
        from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        config = CuratorConfig(enabled=True, consolidation_enabled=True)
        collector = SkillStatsCollector(skills_dir)

        mock_embed = MagicMock()
        mock_embed.embed_batch = AsyncMock(return_value=[])
        mock_llm = MagicMock()
        mock_write = MagicMock()

        curator = SkillCurator(
            collector, config,
            embedding_service=mock_embed,
            llm=mock_llm,
            write_backend=mock_write,
        )
        assert curator.consolidation_available

        skills = [_make_skill(f"skill_{i}") for i in range(3)]
        result, _consolidation = await curator.run_async(skills)
        assert result.skills_scanned == 3
