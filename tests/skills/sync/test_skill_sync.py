"""Skill sync subsystem unit tests.

Covers: ThresholdQualityGate, SkillSyncManifest, LocalFSSyncBackend,
        SkillSyncManager, idle_integration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.sync.quality_gate import ThresholdQualityGate
from myrm_agent_harness.agent.skills.sync.manifest import SkillSyncManifest
from myrm_agent_harness.agent.skills.sync.types import (
    ConflictResolution,
    ConflictStrategy,
    GateVerdict,
    PullResult,
    PushResult,
    RemoteSkillEntry,
    SyncDirection,
    SyncStatus,
)


# ──────────────────────────────────────────────
#  ThresholdQualityGate
# ──────────────────────────────────────────────

class TestThresholdQualityGate:
    """ThresholdQualityGate 单元测试."""

    @pytest.fixture
    def gate(self) -> ThresholdQualityGate:
        return ThresholdQualityGate(min_executions=3, min_effective_rate=0.7)

    @pytest.mark.asyncio
    async def test_pass_with_good_metrics(self, gate: ThresholdQualityGate) -> None:
        verdict = await gate.evaluate("test_skill", "# Skill\ncontent", 0.9, 10)
        assert verdict.passed is True
        assert verdict.score == pytest.approx(0.9)
        assert verdict.reasons == []

    @pytest.mark.asyncio
    async def test_reject_empty_content(self, gate: ThresholdQualityGate) -> None:
        verdict = await gate.evaluate("empty", "", 1.0, 100)
        assert verdict.passed is False
        assert any("Empty" in r for r in verdict.reasons)

    @pytest.mark.asyncio
    async def test_reject_whitespace_only(self, gate: ThresholdQualityGate) -> None:
        verdict = await gate.evaluate("ws", "   \n  ", 1.0, 100)
        assert verdict.passed is False

    @pytest.mark.asyncio
    async def test_reject_low_executions(self, gate: ThresholdQualityGate) -> None:
        verdict = await gate.evaluate("few_runs", "# Skill", 0.9, 2)
        assert verdict.passed is False
        assert any("Insufficient" in r for r in verdict.reasons)

    @pytest.mark.asyncio
    async def test_reject_low_effective_rate(self, gate: ThresholdQualityGate) -> None:
        verdict = await gate.evaluate("low_rate", "# Skill", 0.3, 10)
        assert verdict.passed is False
        assert any("Low effective rate" in r for r in verdict.reasons)

    @pytest.mark.asyncio
    async def test_reject_both_insufficient_and_low_rate(self, gate: ThresholdQualityGate) -> None:
        verdict = await gate.evaluate("bad", "# Skill", 0.1, 1)
        assert verdict.passed is False
        assert len(verdict.reasons) == 2

    @pytest.mark.asyncio
    async def test_boundary_exact_thresholds(self, gate: ThresholdQualityGate) -> None:
        verdict = await gate.evaluate("boundary", "# Skill", 0.7, 3)
        assert verdict.passed is True

    @pytest.mark.asyncio
    async def test_custom_thresholds(self) -> None:
        strict = ThresholdQualityGate(min_executions=10, min_effective_rate=0.95)
        verdict = await strict.evaluate("s", "# Skill", 0.9, 9)
        assert verdict.passed is False


# ──────────────────────────────────────────────
#  SkillSyncManifest
# ──────────────────────────────────────────────

class TestSkillSyncManifest:
    """SkillSyncManifest SQLite 持久化状态测试."""

    @pytest.fixture
    def manifest(self, tmp_path: Path) -> SkillSyncManifest:
        return SkillSyncManifest(tmp_path / "sync.db")

    def test_update_local_new_skill(self, manifest: SkillSyncManifest) -> None:
        manifest.update_local("my_skill", "sha_abc", "1.0.0")
        assert manifest.get_local_sha256("my_skill") == "sha_abc"
        pending = manifest.get_pending_push()
        assert "my_skill" in pending

    def test_update_local_existing_skill(self, manifest: SkillSyncManifest) -> None:
        manifest.update_local("sk", "sha1", "1.0.0")
        manifest.update_local("sk", "sha2", "1.0.1")
        assert manifest.get_local_sha256("sk") == "sha2"

    def test_update_remote_new_skill(self, manifest: SkillSyncManifest) -> None:
        manifest.update_remote("remote_sk", "rsha", "2.0.0")
        pending_pull = manifest.get_pending_pull()
        assert "remote_sk" in pending_pull

    def test_mark_pushed(self, manifest: SkillSyncManifest) -> None:
        manifest.update_local("sk", "sha1")
        assert "sk" in manifest.get_pending_push()
        manifest.mark_pushed("sk")
        assert "sk" not in manifest.get_pending_push()

    def test_mark_synced(self, manifest: SkillSyncManifest) -> None:
        manifest.update_local("sk", "sha_old")
        manifest.mark_synced("sk", "sha_new")
        assert manifest.get_local_sha256("sk") == "sha_new"
        assert "sk" not in manifest.get_pending_push()

    def test_get_conflicts(self, manifest: SkillSyncManifest) -> None:
        conflicts = manifest.get_conflicts()
        assert conflicts == []

    def test_sync_time_tracking(self, manifest: SkillSyncManifest) -> None:
        assert manifest.get_last_sync_time() is None
        now = datetime.now(UTC)
        manifest.set_last_sync_time(now)
        stored = manifest.get_last_sync_time()
        assert stored is not None
        assert abs((stored - now).total_seconds()) < 1

    def test_get_sync_counts(self, manifest: SkillSyncManifest) -> None:
        manifest.update_local("a", "sha_a")
        manifest.update_local("b", "sha_b")
        manifest.update_remote("c", "sha_c")
        counts = manifest.get_sync_counts()
        assert counts.get("local_only", 0) == 2
        assert counts.get("remote_ahead", 0) == 1

    def test_unknown_skill_sha256(self, manifest: SkillSyncManifest) -> None:
        assert manifest.get_local_sha256("nonexistent") == ""

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        db = tmp_path / "persist.db"
        m1 = SkillSyncManifest(db)
        m1.update_local("persistent", "sha_p")
        m2 = SkillSyncManifest(db)
        assert m2.get_local_sha256("persistent") == "sha_p"


# ──────────────────────────────────────────────
#  Data Types
# ──────────────────────────────────────────────

class TestSyncTypes:
    """数据类型正确性测试."""

    def test_gate_verdict_immutable(self) -> None:
        v = GateVerdict(passed=True, score=0.9, reasons=[])
        with pytest.raises(AttributeError):
            v.passed = False  # type: ignore[misc]

    def test_push_result_defaults(self) -> None:
        r = PushResult(success=True)
        assert r.pushed_count == 0
        assert r.rejected_count == 0
        assert r.rejected_skills == []
        assert r.error == ""

    def test_pull_result_defaults(self) -> None:
        r = PullResult(success=True)
        assert r.new_count == 0
        assert r.updated_count == 0
        assert r.conflict_count == 0

    def test_remote_skill_entry_immutable(self) -> None:
        e = RemoteSkillEntry(name="sk", version="1.0", content_sha256="abc")
        with pytest.raises(AttributeError):
            e.name = "other"  # type: ignore[misc]

    def test_conflict_resolution(self) -> None:
        cr = ConflictResolution(
            skill_name="sk",
            strategy_used=ConflictStrategy.NEWER_WINS,
            winner_sha256="abc",
        )
        assert cr.strategy_used == ConflictStrategy.NEWER_WINS

    def test_sync_direction_values(self) -> None:
        assert SyncDirection.PUSH == "push"
        assert SyncDirection.PULL == "pull"

    def test_conflict_strategy_values(self) -> None:
        assert ConflictStrategy.REMOTE_WINS == "remote_wins"
        assert ConflictStrategy.LOCAL_WINS == "local_wins"
        assert ConflictStrategy.NEWER_WINS == "newer_wins"
        assert ConflictStrategy.SKIP == "skip"

    def test_sync_status_mutable(self) -> None:
        s = SyncStatus()
        assert s.enabled is False
        s.enabled = True
        assert s.enabled is True


# ──────────────────────────────────────────────
#  LocalFSSyncBackend
# ──────────────────────────────────────────────

class TestLocalFSSyncBackend:
    """LocalFSSyncBackend 本地文件同步测试."""

    @pytest.fixture
    def mock_storage(self) -> AsyncMock:
        storage = AsyncMock()
        storage._manifest: dict[str, Any] = {}
        storage._files: dict[str, bytes] = {}

        async def write(key: str, content: bytes, content_type: str | None = None) -> None:
            storage._files[key] = content

        async def read(key: str) -> bytes:
            if key not in storage._files:
                raise FileNotFoundError(key)
            return storage._files[key]

        async def write_text(key: str, content: str, encoding: str = "utf-8", content_type: str | None = None) -> None:
            storage._files[key] = content.encode(encoding)

        async def read_text(key: str, encoding: str = "utf-8") -> str:
            if key not in storage._files:
                raise FileNotFoundError(key)
            return storage._files[key].decode(encoding)

        storage.write = AsyncMock(side_effect=write)
        storage.read = AsyncMock(side_effect=read)
        storage.write_text = AsyncMock(side_effect=write_text)
        storage.read_text = AsyncMock(side_effect=read_text)
        return storage

    @pytest.fixture
    def backend(self, mock_storage: AsyncMock, tmp_path: Path) -> Any:
        from myrm_agent_harness.agent.skills.sync.local_sync import LocalFSSyncBackend
        return LocalFSSyncBackend(storage=mock_storage, local_skills_path=tmp_path / "skills")

    @pytest.mark.asyncio
    async def test_push_single_skill(self, backend: Any, mock_storage: AsyncMock) -> None:
        result = await backend.push_skills({"skill_a": b"zipdata"})
        assert result.success is True
        assert result.pushed_count == 1
        assert "shared_skills/skill_a.zip" in mock_storage._files
        assert mock_storage.write_text.called

    @pytest.mark.asyncio
    async def test_push_multiple_skills(self, backend: Any, mock_storage: AsyncMock) -> None:
        bundles = {f"sk_{i}": f"zip_{i}".encode() for i in range(5)}
        result = await backend.push_skills(bundles)
        assert result.success is True
        assert result.pushed_count == 5

    @pytest.mark.asyncio
    async def test_list_remote_empty(self, backend: Any) -> None:
        entries = await backend.list_remote()
        assert entries == []

    @pytest.mark.asyncio
    async def test_list_remote_after_push(self, backend: Any) -> None:
        await backend.push_skills({"sk_a": b"zip_a"})
        entries = await backend.list_remote()
        assert len(entries) == 1
        assert entries[0].name == "sk_a"

    @pytest.mark.asyncio
    async def test_list_remote_with_prefix_filter(self, backend: Any) -> None:
        await backend.push_skills({"data/etl": b"z1", "infra/monitor": b"z2"})
        entries = await backend.list_remote(prefix="data/")
        assert len(entries) == 1
        assert entries[0].name == "data/etl"

    @pytest.mark.asyncio
    async def test_resolve_conflict_remote_wins(self, backend: Any) -> None:
        cr = await backend.resolve_conflict("sk", "local_sha", "remote_sha", ConflictStrategy.REMOTE_WINS)
        assert cr.winner_sha256 == "remote_sha"
        assert cr.strategy_used == ConflictStrategy.REMOTE_WINS

    @pytest.mark.asyncio
    async def test_resolve_conflict_local_wins(self, backend: Any) -> None:
        cr = await backend.resolve_conflict("sk", "local_sha", "remote_sha", ConflictStrategy.LOCAL_WINS)
        assert cr.winner_sha256 == "local_sha"

    @pytest.mark.asyncio
    async def test_resolve_conflict_skip(self, backend: Any) -> None:
        cr = await backend.resolve_conflict("sk", "local_sha", "remote_sha", ConflictStrategy.SKIP)
        assert cr.strategy_used == ConflictStrategy.SKIP

    @pytest.mark.asyncio
    async def test_pull_from_empty_repo(self, backend: Any) -> None:
        result = await backend.pull_skills()
        assert result.success is True
        assert result.new_count == 0


# ──────────────────────────────────────────────
#  SkillSyncManager
# ──────────────────────────────────────────────

class TestSkillSyncManager:
    """SkillSyncManager 编排测试."""

    @pytest.fixture
    def manifest(self, tmp_path: Path) -> SkillSyncManifest:
        return SkillSyncManifest(tmp_path / "manager_sync.db")

    @pytest.fixture
    def skills_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "workspace_skills"
        d.mkdir()
        return d

    @pytest.fixture
    def mock_backend(self) -> AsyncMock:
        backend = AsyncMock()
        backend.push_skills = AsyncMock(
            return_value=PushResult(success=True, pushed_count=1)
        )
        backend.pull_skills = AsyncMock(
            return_value=PullResult(success=True, new_count=1, pulled_skills=["remote_skill"])
        )
        backend.list_remote = AsyncMock(return_value=[])
        return backend

    @pytest.fixture
    def manager(
        self,
        mock_backend: AsyncMock,
        manifest: SkillSyncManifest,
        skills_dir: Path,
    ) -> Any:
        from myrm_agent_harness.agent.skills.sync.manager import SkillSyncManager
        return SkillSyncManager(
            sync_backend=mock_backend,
            manifest=manifest,
            workspace_skills_path=skills_dir,
        )

    @pytest.mark.asyncio
    async def test_get_status_initial(self, manager: Any) -> None:
        status = await manager.get_status()
        assert status.enabled is True
        assert status.pending_push_count == 0
        assert status.pending_pull_count == 0
        assert status.is_syncing is False

    @pytest.mark.asyncio
    async def test_push_no_pending(self, manager: Any) -> None:
        result = await manager.push_evolved_skills()
        assert result.success is True
        assert result.pushed_count == 0

    @pytest.mark.asyncio
    async def test_push_with_pending_skill(
        self,
        manager: Any,
        manifest: SkillSyncManifest,
        skills_dir: Path,
        mock_backend: AsyncMock,
    ) -> None:
        skill_dir = skills_dir / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# My Skill\ncontent here")
        manifest.update_local("my_skill", "sha123")

        with patch.object(manager, "_packer") as mock_packer:
            mock_packer.package_files.return_value = MagicMock(
                success=True, zip_content=b"packed"
            )
            result = await manager.push_evolved_skills()

        assert mock_backend.push_skills.called
        assert result.success is True

    @pytest.mark.asyncio
    async def test_push_rejected_by_quality_gate(
        self,
        manager: Any,
        manifest: SkillSyncManifest,
        skills_dir: Path,
    ) -> None:
        skill_dir = skills_dir / "bad_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Bad Skill")
        manifest.update_local("bad_skill", "sha_bad")

        result = await manager.push_evolved_skills(
            skill_metrics={"bad_skill": (0.1, 1)}
        )
        assert "bad_skill" in result.rejected_skills

    @pytest.mark.asyncio
    async def test_pull_shared_skills(
        self,
        manager: Any,
        skills_dir: Path,
    ) -> None:
        (skills_dir / "remote_skill").mkdir(parents=True, exist_ok=True)
        result = await manager.pull_shared_skills()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_full_sync(
        self,
        manager: Any,
    ) -> None:
        push_result, pull_result = await manager.full_sync()
        assert push_result.success is True
        assert pull_result.success is True

    @pytest.mark.asyncio
    async def test_register_local_skill(
        self,
        manager: Any,
        manifest: SkillSyncManifest,
        skills_dir: Path,
    ) -> None:
        skill_dir = skills_dir / "registered"
        skill_dir.mkdir()
        content = "# Registered Skill"
        (skill_dir / "SKILL.md").write_text(content)

        manager.register_local_skill("registered")
        expected_sha = hashlib.sha256(content.encode()).hexdigest()
        assert manifest.get_local_sha256("registered") == expected_sha

    @pytest.mark.asyncio
    async def test_concurrent_sync_rejected(self, manager: Any) -> None:
        """Verify second sync is rejected when one is in progress."""
        async with manager._sync_lock:
            result = await manager.push_evolved_skills()
            assert result.success is False
            assert "already in progress" in result.error


# ──────────────────────────────────────────────
#  idle_integration
# ──────────────────────────────────────────────

class TestIdleIntegration:
    """idle_integration 空闲任务集成测试."""

    def test_register_handler(self) -> None:
        from myrm_agent_harness.agent.skills.sync import idle_integration

        mock_manager = MagicMock()
        with patch(
            "myrm_agent_harness.agent.background_worker.idle_tasks.register_idle_task_handler"
        ) as mock_reg:
            idle_integration.register_skill_sync_idle_handler(mock_manager)
            mock_reg.assert_called_once_with("skill_sync", idle_integration._handle_skill_sync)

    @pytest.mark.asyncio
    async def test_handle_without_manager(self) -> None:
        from myrm_agent_harness.agent.skills.sync import idle_integration

        idle_integration._sync_manager_ref = None
        mock_task = MagicMock()
        result = await idle_integration._handle_skill_sync(mock_task, "session_1")
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_handle_with_valid_manager(self) -> None:
        from myrm_agent_harness.agent.skills.sync.manager import SkillSyncManager
        from myrm_agent_harness.agent.skills.sync import idle_integration

        mock_manager = MagicMock(spec=SkillSyncManager)
        mock_manager.is_syncing = False
        mock_manager.full_sync = AsyncMock(
            return_value=(
                PushResult(success=True, pushed_count=2),
                PullResult(success=True, new_count=1, updated_count=0),
            )
        )

        idle_integration._sync_manager_ref = mock_manager
        mock_task = MagicMock()
        result = await idle_integration._handle_skill_sync(mock_task, "session_2")

        assert result["push_success"] is True
        assert result["push_count"] == 2
        assert result["pull_success"] is True
        assert result["pull_new"] == 1

    @pytest.mark.asyncio
    async def test_handle_skips_when_syncing(self) -> None:
        from myrm_agent_harness.agent.skills.sync.manager import SkillSyncManager
        from myrm_agent_harness.agent.skills.sync import idle_integration

        mock_manager = MagicMock(spec=SkillSyncManager)
        mock_manager.is_syncing = True

        idle_integration._sync_manager_ref = mock_manager
        mock_task = MagicMock()
        result = await idle_integration._handle_skill_sync(mock_task, "session_3")
        assert result["skipped"] is True

    def test_task_type_constant(self) -> None:
        from myrm_agent_harness.agent.skills.sync.idle_integration import SKILL_SYNC_TASK_TYPE
        assert SKILL_SYNC_TASK_TYPE == "skill_sync"
