"""Unit tests for evolution lock (pinned skill) mechanism.

Tests cover:
1. engine.fix_skill skips locked skills (defense-in-depth)
2. engine.derive_skill_simple skips locked skills (defense-in-depth)
3. store.set_evolution_lock / is_evolution_locked round-trip
4. skill_manage_tool lock/unlock actions via _handle_evolution_lock
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillLineage,
    SkillMetrics,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore


def _make_skill(*, locked: bool = False) -> SkillRecord:
    """Create a test SkillRecord with optional evolution lock."""
    return SkillRecord(
        skill_id="test_skill_v1",
        name="test_skill",
        description="Test skill",
        content="# Test\nHello",
        path="/tmp/test_skill/SKILL.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        metrics=SkillMetrics(applied_count=5, success_count=1, consecutive_failures=3),
        evolution_locked=locked,
    )


class TestEngineLockDefenseInDepth:
    """Test that fix_skill and derive_skill_simple check evolution_locked directly."""

    def setup_method(self):
        self.store = MagicMock(spec=SkillStore)
        self.llm = MagicMock()
        self.engine = SkillEvolutionEngine(self.store, self.llm, None)

    @pytest.mark.asyncio
    async def test_fix_skill_skips_locked(self):
        """fix_skill must return None for locked skills without calling LLM."""
        locked_skill = _make_skill(locked=True)
        self.store.get_skill.return_value = locked_skill

        result = await self.engine.fix_skill("test_skill_v1", "some error")

        assert result is None
        self.llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_fix_skill_proceeds_for_unlocked(self):
        """fix_skill should proceed normally for unlocked skills."""
        unlocked_skill = _make_skill(locked=False)
        self.store.get_skill.return_value = unlocked_skill
        self.store.get_evolution_constraints.return_value = []
        self.store.search_skills = AsyncMock(return_value=[])

        mock_response = MagicMock()
        mock_response.content = "fixed content"
        self.llm.ainvoke = AsyncMock(return_value=mock_response)

        await self.engine.fix_skill("test_skill_v1", "some error")
        self.llm.ainvoke.assert_called()

    @pytest.mark.asyncio
    async def test_derive_skill_skips_locked(self):
        """derive_skill_simple must return None for locked skills."""
        locked_skill = _make_skill(locked=True)
        self.store.get_skill.return_value = locked_skill

        result = await self.engine.derive_skill_simple("test_skill_v1", "make it faster")

        assert result is None
        self.llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_fix_skill_not_found(self):
        """fix_skill returns None when skill not found."""
        self.store.get_skill.return_value = None
        result = await self.engine.fix_skill("nonexistent", "error")
        assert result is None


class TestStoreEvolutionLock:
    """Test SkillStore evolution lock operations with real SQLite."""

    @pytest.fixture
    def store(self, tmp_path: Path):
        db_path = tmp_path / "test_skills.db"
        s = SkillStore(db_path=db_path)
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_lock_unlock_round_trip(self, store: SkillStore):
        """Lock and unlock should persist correctly."""
        skill = _make_skill(locked=False)
        await store.save_skill(skill)

        assert not store.is_evolution_locked("test_skill_v1")

        await store.set_evolution_lock("test_skill_v1", locked=True)
        assert store.is_evolution_locked("test_skill_v1")

        await store.set_evolution_lock("test_skill_v1", locked=False)
        assert not store.is_evolution_locked("test_skill_v1")

    @pytest.mark.asyncio
    async def test_lock_nonexistent_skill(self, store: SkillStore):
        """is_evolution_locked returns False for nonexistent skills."""
        assert not store.is_evolution_locked("nonexistent_skill")

    @pytest.mark.asyncio
    async def test_save_preserves_lock_state(self, store: SkillStore):
        """Saving a locked skill should preserve the lock state."""
        skill = _make_skill(locked=True)
        await store.save_skill(skill)

        loaded = store.get_skill("test_skill_v1")
        assert loaded is not None
        assert loaded.evolution_locked is True

    @pytest.mark.asyncio
    async def test_lock_persists_across_reads(self, store: SkillStore):
        """Lock set via set_evolution_lock should be visible in get_skill."""
        skill = _make_skill(locked=False)
        await store.save_skill(skill)

        await store.set_evolution_lock("test_skill_v1", locked=True)

        loaded = store.get_skill("test_skill_v1")
        assert loaded is not None
        assert loaded.evolution_locked is True


class TestHandleEvolutionLock:
    """Test _handle_evolution_lock function directly."""

    @pytest.mark.asyncio
    async def test_lock_success(self):
        """Lock action should succeed when evolution system is available."""
        from myrm_agent_harness.agent.meta_tools.skills.manage.skill_manage_tool import _handle_evolution_lock

        mock_store = MagicMock(spec=SkillStore)
        mock_store.get_skill.return_value = _make_skill(locked=False)
        mock_store.set_evolution_lock = AsyncMock()

        mock_evolution = MagicMock()
        mock_evolution.store = mock_store

        with patch(
            "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
            return_value=mock_evolution,
        ):
            result = await _handle_evolution_lock("test_skill", locked=True)

        assert "locked successfully" in result
        assert "disabled" in result
        mock_store.set_evolution_lock.assert_called_once_with("test_skill_v1", locked=True)

    @pytest.mark.asyncio
    async def test_unlock_success(self):
        """Unlock action should succeed."""
        from myrm_agent_harness.agent.meta_tools.skills.manage.skill_manage_tool import _handle_evolution_lock

        mock_store = MagicMock(spec=SkillStore)
        mock_store.get_skill.return_value = _make_skill(locked=True)
        mock_store.set_evolution_lock = AsyncMock()

        mock_evolution = MagicMock()
        mock_evolution.store = mock_store

        with patch(
            "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
            return_value=mock_evolution,
        ):
            result = await _handle_evolution_lock("test_skill", locked=False)

        assert "unlocked successfully" in result
        assert "re-enabled" in result

    @pytest.mark.asyncio
    async def test_lock_no_evolution_system(self):
        """Lock should fail gracefully when evolution system is not initialized."""
        from myrm_agent_harness.agent.meta_tools.skills.manage.skill_manage_tool import _handle_evolution_lock

        with patch(
            "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
            return_value=None,
        ):
            result = await _handle_evolution_lock("test_skill", locked=True)

        assert "Error" in result
        assert "not initialized" in result

    @pytest.mark.asyncio
    async def test_lock_skill_not_found(self):
        """Lock should fail when skill doesn't exist in store."""
        from myrm_agent_harness.agent.meta_tools.skills.manage.skill_manage_tool import _handle_evolution_lock

        mock_store = MagicMock(spec=SkillStore)
        mock_store.get_skill.return_value = None

        mock_evolution = MagicMock()
        mock_evolution.store = mock_store

        with patch(
            "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
            return_value=mock_evolution,
        ):
            result = await _handle_evolution_lock("nonexistent", locked=True)

        assert "Error" in result
        assert "not found" in result
