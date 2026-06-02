"""Tests for SkillSyncManager — orchestrator integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.sync.manager import SkillSyncManager
from myrm_agent_harness.agent.skills.sync.manifest import SkillSyncManifest
from myrm_agent_harness.agent.skills.sync.quality_gate import ThresholdQualityGate
from myrm_agent_harness.agent.skills.sync.types import PullResult, PushResult


class FakeSyncBackend:
    """Fake sync backend for testing."""

    def __init__(self) -> None:
        self.pushed: dict[str, bytes] = {}

    async def push_skills(self, bundles: dict[str, bytes]) -> PushResult:
        self.pushed.update(bundles)
        return PushResult(success=True, pushed_count=len(bundles))

    async def pull_skills(self, since_version: str = "", name_filter: str = "") -> PullResult:
        return PullResult(success=True, new_count=0, updated_count=0)

    async def list_remote(self, prefix: str = "") -> list:
        return []

    async def resolve_conflict(self, skill_name: str, local_sha256: str, remote_sha256: str, strategy=None):
        from myrm_agent_harness.agent.skills.sync.types import ConflictResolution, ConflictStrategy

        return ConflictResolution(
            skill_name=skill_name,
            strategy_used=ConflictStrategy.LOCAL_WINS,
            winner_sha256=local_sha256,
        )


@pytest.fixture
def skill_workspace(tmp_path: Path) -> Path:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    skill_a = skills_dir / "skill_a"
    skill_a.mkdir()
    (skill_a / "SKILL.md").write_text("---\nname: skill_a\nversion: 1.0.0\n---\n\n# Skill A\nDoes things.")
    return skills_dir


@pytest.fixture
def manager(tmp_path: Path, skill_workspace: Path) -> tuple[SkillSyncManager, FakeSyncBackend]:
    manifest = SkillSyncManifest(tmp_path / "sync.db")
    backend = FakeSyncBackend()
    mgr = SkillSyncManager(
        sync_backend=backend,
        manifest=manifest,
        workspace_skills_path=skill_workspace,
        quality_gate=ThresholdQualityGate(),
    )
    return mgr, backend


@pytest.mark.asyncio
async def test_register_and_push(manager: tuple[SkillSyncManager, FakeSyncBackend], skill_workspace: Path) -> None:
    mgr, backend = manager
    mgr.register_local_skill("skill_a")

    result = await mgr.push_evolved_skills(
        skill_metrics={"skill_a": (0.9, 10)}
    )
    assert result.success is True
    assert result.pushed_count == 1
    assert "skill_a" in backend.pushed


@pytest.mark.asyncio
async def test_push_rejects_low_quality(manager: tuple[SkillSyncManager, FakeSyncBackend]) -> None:
    mgr, _backend = manager
    mgr.register_local_skill("skill_a")

    result = await mgr.push_evolved_skills(
        skill_metrics={"skill_a": (0.2, 1)}
    )
    assert result.success is True
    assert result.pushed_count == 0
    assert result.rejected_count > 0


@pytest.mark.asyncio
async def test_pull_shared_skills(manager: tuple[SkillSyncManager, FakeSyncBackend]) -> None:
    mgr, _ = manager
    result = await mgr.pull_shared_skills()
    assert result.success is True


@pytest.mark.asyncio
async def test_full_sync(manager: tuple[SkillSyncManager, FakeSyncBackend]) -> None:
    mgr, _ = manager
    mgr.register_local_skill("skill_a")
    push_result, pull_result = await mgr.full_sync(
        skill_metrics={"skill_a": (0.85, 5)}
    )
    assert push_result.success
    assert pull_result.success


@pytest.mark.asyncio
async def test_concurrent_sync_prevention(manager: tuple[SkillSyncManager, FakeSyncBackend]) -> None:
    mgr, _ = manager
    # Simulate a lock being held
    await mgr._sync_lock.acquire()
    try:
        result = await mgr.push_evolved_skills()
        assert result.success is False
        assert "already in progress" in result.error
    finally:
        mgr._sync_lock.release()


@pytest.mark.asyncio
async def test_get_status(manager: tuple[SkillSyncManager, FakeSyncBackend]) -> None:
    mgr, _ = manager
    mgr.register_local_skill("skill_a")
    status = await mgr.get_status()
    assert status.enabled is True
    assert status.pending_push_count == 1
    assert status.is_syncing is False
