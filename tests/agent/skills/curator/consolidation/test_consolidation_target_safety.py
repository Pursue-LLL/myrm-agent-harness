"""Consolidation treats every skill name the LLM proposes as untrusted.

A proposed umbrella name may collide with a skill that exists (a pinned one, one a host protects, one in the
cluster itself); a proposed merge or demote target may not exist at all. The write backend would carry out all
of these: save over the existing skill, or archive the sources into a skill that was never written. The write
backend here behaves like the host's: it replaces an existing skill on save and reports a failed resource write
by returning a failure, not by raising.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.curator.consolidation.executor import ConsolidationExecutor
from myrm_agent_harness.agent.skills.curator.consolidation.judge import ConsolidationJudge, _ClusterJudgment
from myrm_agent_harness.agent.skills.curator.consolidation.orchestrator import SkillConsolidator
from myrm_agent_harness.agent.skills.curator.consolidation.types import (
    ConsolidationAction,
    ConsolidationActionType,
    ConsolidationPlan,
    SkillCluster,
)
from myrm_agent_harness.agent.skills.curator.engine import SkillCurator
from myrm_agent_harness.backends.skills.creation_protocols import SkillResourceWriteResult, SkillSaveResult
from myrm_agent_harness.backends.skills.curator_config import CuratorConfig
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata

_USER_BODY = "# git_operations\n\nRule 1: never force push.\nRule 2: rebase before merge.\nRule 3: sign commits.\n"
_CLUSTER_NAMES = ("deploy_docker", "deploy_k8s", "deploy_ec2")


class _DiskWriteBackend:
    """Write backend that mirrors the host: save replaces, a failed resource write is a returned failure."""

    def __init__(self, root: Path, *, fail_resources: bool = False) -> None:
        self._root = root
        self._fail_resources = fail_resources

    async def save_skill(self, name: str, content: str, description: str) -> SkillSaveResult:
        skill_dir = self._root / name
        existed = skill_dir.is_dir()
        skill_dir.mkdir(exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return SkillSaveResult(success=True, skill_name=name, saved_path=str(skill_dir), was_updated=existed)

    async def write_resource(self, skill_name: str, resource_path: str, content: str) -> SkillResourceWriteResult:
        skill_dir = self._root / skill_name
        if self._fail_resources or not skill_dir.is_dir():
            return SkillResourceWriteResult(
                success=False,
                skill_name=skill_name,
                resource_path=resource_path,
                error=f"Skill '{skill_name}' not found",
            )
        target = skill_dir / resource_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return SkillResourceWriteResult(success=True, skill_name=skill_name, resource_path=resource_path)


def _seed(root: Path, name: str, body: str = "# skill\n") -> SkillMetadata:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return SkillMetadata(name=name, description=f"{name} skill", storage_path=str(skill_dir))


def _is_archived(skill: SkillMetadata) -> bool:
    ledger = Path(skill.storage_path or "") / ".stats.json"
    return ledger.exists() and json.loads(ledger.read_text(encoding="utf-8"))["lifecycle_status"] == "archived"


def _llm_judging(action: str, target: str) -> MagicMock:
    judgment = _ClusterJudgment(
        action=action,  # type: ignore[arg-type]
        target_skill_name=target,
        reasoning="same domain",
        umbrella_description="Umbrella",
    )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(return_value=judgment)))
    return llm


@pytest.fixture
def root(tmp_path: Path) -> Path:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    return skills_root


@pytest.fixture
def collector() -> SkillStatsCollector:
    return SkillStatsCollector()


def _umbrella(target: str, sources: Sequence[str]) -> ConsolidationAction:
    return ConsolidationAction(
        action_type=ConsolidationActionType.CREATE_UMBRELLA,
        target_skill=target,
        source_skills=tuple(sources),
        reasoning="same domain",
        umbrella_description="Git operations",
    )


class TestExecutorNeverWritesToAnOccupiedName:
    @pytest.mark.parametrize(
        ("occupant_name", "target", "reserved"),
        [
            pytest.param("git_operations", "git_operations", frozenset[str](), id="a-candidate-outside-the-sources"),
            pytest.param("git_operations", "Git_Operations", frozenset[str](), id="the-target-differs-only-in-case"),
            pytest.param("Git_Operations", "git_operations", frozenset[str](), id="the-occupant-differs-only-in-case"),
            pytest.param("git_operations", "git_operations", frozenset({"git_operations"}), id="a-reserved-name"),
        ],
    )
    async def test_umbrella_leaves_the_occupant_and_the_sources_alone(
        self, root: Path, collector: SkillStatsCollector, occupant_name: str, target: str, reserved: frozenset[str]
    ) -> None:
        occupant = _seed(root, occupant_name, _USER_BODY)
        commit, push = _seed(root, "git_commit"), _seed(root, "git_push")
        # A reserved skill is one the host keeps out of the run, so the executor is never handed it.
        candidates = [commit, push] if reserved else [occupant, commit, push]
        executor = ConsolidationExecutor(_DiskWriteBackend(root), collector, candidates, reserved_names=reserved)

        report = await executor.execute([_umbrella(target, ("git_commit", "git_push"))])

        assert (report.success_count, report.failure_count) == (0, 1)
        assert "already taken" in report.results[0].error
        assert (root / occupant_name / "SKILL.md").read_text(encoding="utf-8") == _USER_BODY
        assert not _is_archived(commit)
        assert not _is_archived(push)

    async def test_umbrella_with_a_free_name_is_still_created(self, root: Path, collector: SkillStatsCollector) -> None:
        commit, push = _seed(root, "git_commit"), _seed(root, "git_push")
        executor = ConsolidationExecutor(
            _DiskWriteBackend(root), collector, [commit, push], reserved_names=frozenset({"deploy_ops"})
        )

        report = await executor.execute([_umbrella("git_operations", ("git_commit", "git_push"))])

        assert report.success_count == 1
        assert (root / "git_operations" / "SKILL.md").is_file()
        assert _is_archived(commit)
        assert _is_archived(push)


class TestExecutorArchivesOnlyWhatLanded:
    async def test_demote_to_an_unknown_target_archives_nothing(
        self, root: Path, collector: SkillStatsCollector
    ) -> None:
        split, merge = _seed(root, "pdf_split"), _seed(root, "pdf_merge")
        action = ConsolidationAction(
            action_type=ConsolidationActionType.DEMOTE,
            target_skill="ghost_pdf_toolkit",
            source_skills=("pdf_split", "pdf_merge"),
            reasoning="narrow helpers",
        )

        report = await ConsolidationExecutor(_DiskWriteBackend(root), collector, [split, merge]).execute([action])

        assert (report.success_count, report.failure_count) == (0, 1)
        assert "not found" in report.results[0].error
        assert not (root / "ghost_pdf_toolkit").exists()
        assert not _is_archived(split)
        assert not _is_archived(merge)

    @pytest.mark.parametrize("action_type", [ConsolidationActionType.MERGE, ConsolidationActionType.DEMOTE])
    async def test_a_failed_resource_write_keeps_the_sources_active(
        self, root: Path, collector: SkillStatsCollector, action_type: ConsolidationActionType
    ) -> None:
        main, helper = _seed(root, "pdf_toolkit"), _seed(root, "pdf_split")
        action = ConsolidationAction(
            action_type=action_type,
            target_skill="pdf_toolkit",
            source_skills=("pdf_split",),
            reasoning="narrow helper",
        )
        executor = ConsolidationExecutor(_DiskWriteBackend(root, fail_resources=True), collector, [main, helper])

        report = await executor.execute([action])

        assert (report.success_count, report.failure_count) == (0, 1)
        assert "Failed to write" in report.results[0].error
        assert not _is_archived(helper)

    @pytest.mark.parametrize("action_type", [ConsolidationActionType.MERGE, ConsolidationActionType.DEMOTE])
    async def test_a_landed_resource_write_archives_the_sources(
        self, root: Path, collector: SkillStatsCollector, action_type: ConsolidationActionType
    ) -> None:
        main, helper = _seed(root, "pdf_toolkit"), _seed(root, "pdf_split")
        action = ConsolidationAction(
            action_type=action_type,
            target_skill="pdf_toolkit",
            source_skills=("pdf_split",),
            reasoning="narrow helper",
        )

        report = await ConsolidationExecutor(_DiskWriteBackend(root), collector, [main, helper]).execute([action])

        assert report.success_count == 1
        assert (root / "pdf_toolkit" / "references" / "pdf_split.md").is_file()
        assert _is_archived(helper)


class TestJudgeDropsActionsWithUntrustedTargets:
    @staticmethod
    def _cluster() -> SkillCluster:
        return SkillCluster(
            cluster_id="prefix-deploy", skill_names=_CLUSTER_NAMES, shared_domain="deploy", avg_similarity=0.9
        )

    @staticmethod
    def _skills(root: Path) -> list[SkillMetadata]:
        return [_seed(root, name) for name in (*_CLUSTER_NAMES, "release_notes")]

    @pytest.mark.parametrize(
        ("target", "reserved"),
        [
            pytest.param("deploy_docker", frozenset[str](), id="a-cluster-member"),
            pytest.param("release_notes", frozenset[str](), id="a-candidate-outside-the-cluster"),
            pytest.param("Release_Notes", frozenset[str](), id="a-name-differing-only-in-case"),
            pytest.param("deploy_ops", frozenset({"deploy_ops"}), id="a-reserved-name"),
        ],
    )
    async def test_an_umbrella_named_after_an_existing_skill_is_dropped(
        self, root: Path, target: str, reserved: frozenset[str]
    ) -> None:
        judge = ConsolidationJudge(_llm_judging("create_umbrella", target))

        plan = await judge.judge_clusters([self._cluster()], self._skills(root), reserved_names=reserved)

        assert plan.is_empty

    async def test_an_umbrella_with_a_free_name_is_planned(self, root: Path) -> None:
        judge = ConsolidationJudge(_llm_judging("create_umbrella", "deploy_operations"))

        plan = await judge.judge_clusters(
            [self._cluster()], self._skills(root), reserved_names=frozenset({"git_operations"})
        )

        assert [a.target_skill for a in plan.actions] == ["deploy_operations"]

    @pytest.mark.parametrize("action", ["merge", "demote"])
    async def test_a_target_that_is_not_a_known_skill_is_dropped(self, root: Path, action: str) -> None:
        judge = ConsolidationJudge(_llm_judging(action, "ghost_toolkit"))

        plan = await judge.judge_clusters([self._cluster()], self._skills(root))

        assert plan.is_empty

    async def test_a_merge_into_a_broader_skill_outside_the_cluster_is_kept(self, root: Path) -> None:
        judge = ConsolidationJudge(_llm_judging("merge", "release_notes"))

        plan = await judge.judge_clusters([self._cluster()], self._skills(root))

        assert [(a.target_skill, a.source_skills) for a in plan.actions] == [("release_notes", _CLUSTER_NAMES)]


def _git_skills(root: Path) -> list[SkillMetadata]:
    return [_seed(root, name) for name in ("git_commit_skill", "git_push_skill", "git_merge_skill", "deploy_skill")]


def _embeddings() -> MagicMock:
    embed = MagicMock()
    embed.embed_batch = AsyncMock(return_value=[[0.1] * 128] * 12)
    return embed


class TestReservedNamesReachTheJudgeThroughTheWholePipeline:
    async def test_consolidator_drops_an_umbrella_named_after_a_reserved_skill(
        self, root: Path, collector: SkillStatsCollector
    ) -> None:
        consolidator = SkillConsolidator(
            _embeddings(),
            _llm_judging("create_umbrella", "git_operations"),
            _DiskWriteBackend(root),
            collector,
            min_skills_for_consolidation=3,
            min_cluster_size=3,
            similarity_threshold=0.95,
        )

        plan = await consolidator.run(_git_skills(root), dry_run=True, reserved_names=frozenset({"git_operations"}))

        assert isinstance(plan, ConsolidationPlan)
        assert plan.is_empty

    async def test_curator_reserves_the_skills_it_keeps_out_of_consolidation(
        self, root: Path, collector: SkillStatsCollector
    ) -> None:
        bound = _seed(root, "git_operations", _USER_BODY)
        curator = SkillCurator(
            collector,
            CuratorConfig(
                enabled=True,
                consolidation_enabled=True,
                consolidation_min_skills=3,
                consolidation_min_cluster_size=3,
                consolidation_similarity_threshold=0.95,
            ),
            embedding_service=_embeddings(),
            llm=_llm_judging("create_umbrella", "git_operations"),
            write_backend=_DiskWriteBackend(root),
        )

        _, plan = await curator.run_async(
            [*_git_skills(root), bound], consolidation_dry_run=True, protected_names=frozenset({"git_operations"})
        )

        assert isinstance(plan, ConsolidationPlan)
        assert plan.is_empty
