"""Unit tests for TDE Red-Green testing, Intent Context, types, and integration coverage."""

import tempfile
from contextvars import copy_context
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skill_agent.context import (
    get_task_intent,
    set_task_intent,
)
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionRequest,
    EvolutionType,
    SkillLineage,
    SkillRecord,
)
from myrm_agent_harness.toolkits.code_execution.executors.test_executor import (
    SubprocessCodeExecutor,
)


class TestSubprocessRedGreen:
    """Tests for Red-Green validation in SubprocessCodeExecutor."""

    def setup_method(self) -> None:
        self.executor = SubprocessCodeExecutor(timeout_seconds=30, memory_limit_mb=128)

    @pytest.mark.asyncio
    async def test_red_green_passes_when_old_fails_new_passes(self) -> None:
        """Red-Green should pass: test fails on old code, passes on new code."""
        old_content = '"""Old skill that raises."""\nraise ValueError("bug")'
        new_content = '"""Fixed skill."""\nresult = 42'
        test_code = """
import os
def test_no_error():
    content = open(os.environ["EVOLUTION_SKILL_PATH"]).read()
    assert "raise" not in content, "Should not contain raise"
"""
        result = await self.executor.run_tests(
            skill_content=new_content,
            test_code=test_code,
            skill_name="test_skill",
            old_skill_content=old_content,
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_red_green_fails_when_old_also_passes(self) -> None:
        """Red-Green violation: test passes on both old and new code."""
        old_content = '"""Old skill."""\nresult = 42'
        new_content = '"""New skill."""\nresult = 42'
        test_code = """
def test_trivial():
    assert True
"""
        result = await self.executor.run_tests(
            skill_content=new_content,
            test_code=test_code,
            skill_name="test_skill",
            old_skill_content=old_content,
        )
        assert result.passed is False
        assert "Red-Green Violation" in result.stderr

    @pytest.mark.asyncio
    async def test_no_red_green_when_old_content_not_provided(self) -> None:
        """Without old_skill_content, skip Red phase, run Green only."""
        new_content = '"""New skill."""\nresult = 42'
        test_code = """
def test_trivial():
    assert True
"""
        result = await self.executor.run_tests(
            skill_content=new_content,
            test_code=test_code,
            skill_name="test_skill",
            old_skill_content=None,
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_red_green_old_timeout_counts_as_red(self) -> None:
        """Old code timeout is treated as failure (Red), Green phase should proceed."""
        old_content = '"""Slow skill."""\nimport time; time.sleep(999)'
        new_content = '"""Fast skill."""\nresult = 42'
        test_code = """
import os
def test_fast():
    content = open(os.environ["EVOLUTION_SKILL_PATH"]).read()
    assert "time.sleep(999)" not in content
"""
        executor = SubprocessCodeExecutor(timeout_seconds=30, memory_limit_mb=128)
        result = await executor.run_tests(
            skill_content=new_content,
            test_code=test_code,
            skill_name="test_skill",
            old_skill_content=old_content,
        )
        assert result.passed is True


class TestTaskIntentContextVar:
    """Tests for task_intent ContextVar in skill_agent."""

    def test_default_is_empty(self) -> None:
        """Default task_intent should be empty string."""
        ctx = copy_context()
        result = ctx.run(get_task_intent)
        assert result == ""

    def test_set_and_get(self) -> None:
        """set_task_intent should make get_task_intent return the value."""
        ctx = copy_context()

        def _run() -> str:
            set_task_intent("Help me debug the login issue")
            return get_task_intent()

        assert ctx.run(_run) == "Help me debug the login issue"

    def test_context_isolation(self) -> None:
        """ContextVar should be isolated between contexts."""
        ctx1 = copy_context()
        ctx2 = copy_context()

        ctx1.run(set_task_intent, "task A")
        ctx2.run(set_task_intent, "task B")

        assert ctx1.run(get_task_intent) == "task A"
        assert ctx2.run(get_task_intent) == "task B"


# ---------------------------------------------------------------------------
# Types coverage
# ---------------------------------------------------------------------------


class TestSkillLineage:
    """Cover to_dict / from_dict roundtrip."""

    def test_to_dict(self) -> None:
        lineage = SkillLineage(
            evolution_type=EvolutionType.FIX,
            version=2,
            parent_id="p1",
            change_summary="Fixed bug",
        )
        d = lineage.to_dict()
        assert d["evolution_type"] == "fix"
        assert d["version"] == 2
        assert d["parent_id"] == "p1"

    def test_from_dict(self) -> None:
        d = {
            "evolution_type": "derived",
            "version": 3,
            "parent_id": "p2",
            "change_summary": "Optimized",
            "created_at": "2026-01-01T00:00:00",
            "created_by": "gpt-4o",
        }
        lineage = SkillLineage.from_dict(d)
        assert lineage.evolution_type == EvolutionType.DERIVED
        assert lineage.version == 3
        assert lineage.parent_id == "p2"

    def test_from_dict_minimal(self) -> None:
        d = {"evolution_type": "captured"}
        lineage = SkillLineage.from_dict(d)
        assert lineage.version == 1
        assert lineage.parent_id is None


class TestSkillRecord:
    """Cover to_dict / from_dict roundtrip."""

    def _make_record(self) -> SkillRecord:
        return SkillRecord(
            skill_id="sk1",
            name="test",
            description="desc",
            content="# Skill",
            path="/skills/test",
            lineage=SkillLineage(evolution_type=EvolutionType.FIX),
        )

    def test_to_dict_roundtrip(self) -> None:
        r = self._make_record()
        d = r.to_dict()
        assert d["skill_id"] == "sk1"
        assert "metrics" not in d

        r2 = SkillRecord.from_dict(d)
        assert r2.skill_id == r.skill_id
        assert r2.lineage.evolution_type == EvolutionType.FIX

    def test_from_dict_ignores_legacy_metrics(self) -> None:
        d = {
            "skill_id": "sk2",
            "name": "test",
            "description": "desc",
            "content": "# Test",
            "path": "/p",
            "lineage": {"evolution_type": "captured"},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metrics": {"total_selections": 7, "applied_count": 3},
        }
        r = SkillRecord.from_dict(d)
        assert r.skill_id == "sk2"
        assert not hasattr(r, "metrics")


class TestEvolutionRequest:
    """Cover EvolutionRequest.to_dict."""

    def test_to_dict(self) -> None:
        req = EvolutionRequest(
            evolution_type=EvolutionType.DERIVED,
            skill_id="sk1",
            reason="perf",
            user_feedback="Make faster",
        )
        d = req.to_dict()
        assert d["evolution_type"] == "derived"
        assert d["skill_id"] == "sk1"
        assert d["user_feedback"] == "Make faster"


# ---------------------------------------------------------------------------
# SubprocessExecutor additional coverage
# ---------------------------------------------------------------------------


class TestSubprocessExecutorEdgeCases:
    """Cover regression test copying, new code timeout, and resource limiter."""

    @pytest.mark.asyncio
    async def test_regression_test_copying(self) -> None:
        """Test that existing regression tests from skill_dir are copied."""
        executor = SubprocessCodeExecutor(timeout_seconds=30, memory_limit_mb=128)

        with tempfile.TemporaryDirectory() as skill_dir_path:
            skill_dir = Path(skill_dir_path)
            # Create a regression test file
            (skill_dir / "test_existing.py").write_text("def test_old(): assert True\n", encoding="utf-8")
            # Create a non-test file (should be ignored)
            (skill_dir / "helper.py").write_text("x = 1\n", encoding="utf-8")

            result = await executor.run_tests(
                skill_content='"""Skill."""',
                test_code="def test_new(): assert True\n",
                skill_name="test_skill",
                skill_dir=skill_dir,
            )
            assert result.passed is True

    @pytest.mark.asyncio
    async def test_new_code_timeout(self) -> None:
        """Test that Green phase timeout returns timed_out=True."""
        executor = SubprocessCodeExecutor(timeout_seconds=1, memory_limit_mb=128)

        test_code = """
import time
def test_slow():
    time.sleep(60)
"""
        result = await executor.run_tests(skill_content='"""Skill."""', test_code=test_code, skill_name="test_skill")
        assert result.passed is False
        assert result.timed_out is True
        assert result.returncode == 124
        assert "[Timed out]" in result.stderr

    def test_resource_limiter_returns_callable(self) -> None:
        """_build_resource_limiter should return a callable on Unix."""
        executor = SubprocessCodeExecutor()
        limiter = executor._build_resource_limiter()
        # On macOS/Linux, should return a callable
        assert limiter is not None and callable(limiter)

    def test_resource_limiter_callable_runs(self) -> None:
        """The returned limiter function should execute without errors."""
        executor = SubprocessCodeExecutor(timeout_seconds=5, memory_limit_mb=256)
        limiter = executor._build_resource_limiter()
        if limiter is not None:
            with patch("resource.setrlimit"):
                limiter()  # Should not raise


# ---------------------------------------------------------------------------
# EvolutionIntegration additional coverage
# ---------------------------------------------------------------------------


class TestEvolutionIntegrationMethods:
    """Cover get/set global, evolve_skill, get_stats, close."""

    @pytest.mark.asyncio
    async def test_init_basic(self, tmp_path) -> None:
        """Test basic initialization of EvolutionIntegration."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        db_path = tmp_path / "skills.db"
        mock_llm = MagicMock()
        integration = EvolutionIntegration(db_path=db_path, llm=mock_llm, enable_tde=True, enable_tool_calling=True)

        assert integration.db_path == db_path
        assert integration.store is not None
        assert integration.engine is not None

        await integration.close()

    def test_get_set_global_evolution_integration(self) -> None:
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            get_global_evolution_integration,
            set_global_evolution_integration,
        )

        original = get_global_evolution_integration()
        try:
            mock_integration = MagicMock()
            set_global_evolution_integration(mock_integration)
            assert get_global_evolution_integration() is mock_integration

            set_global_evolution_integration(None)
            assert get_global_evolution_integration() is None
        finally:
            set_global_evolution_integration(original)

    @pytest.mark.asyncio
    async def test_evolve_skill_no_engine(self) -> None:
        """evolve_skill should return None when engine is not initialized."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.engine = None

        result = await integration.evolve_skill("sk1", EvolutionType.FIX, reason="bug")
        assert result is None

    @pytest.mark.asyncio
    async def test_evolve_skill_fix(self) -> None:
        """evolve_skill with FIX type should call engine.fix_skill."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.engine = AsyncMock()
            integration.engine.fix_skill = AsyncMock(return_value="fixed")
            integration.screener = None

        result = await integration.evolve_skill("sk1", EvolutionType.FIX, reason="crash")
        assert result == "fixed"
        integration.engine.fix_skill.assert_awaited_once_with("sk1", "crash")

    @pytest.mark.asyncio
    async def test_evolve_skill_derived(self) -> None:
        """evolve_skill with DERIVED type should call engine.derive_skill_simple."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.engine = AsyncMock()
            integration.engine.derive_skill_simple = AsyncMock(return_value="derived")
            integration.screener = None

        result = await integration.evolve_skill("sk1", EvolutionType.DERIVED, user_feedback="faster")
        assert result == "derived"

    def test_get_stats_minimal(self) -> None:
        """get_stats should return metrics even with no queue."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.metrics_tracker = MagicMock()
            integration.metrics_tracker.get_report.return_value = {"total": 0}
            integration.queue = None

        stats = integration.get_stats()
        assert "metrics" in stats
        assert stats["metrics"]["total"] == 0

    def test_get_stats_with_queue(self) -> None:
        """get_stats should include queue stats when the queue is enabled."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.metrics_tracker = MagicMock()
            integration.metrics_tracker.get_report.return_value = {}
            integration.queue = MagicMock()
            integration.queue.get_stats.return_value = {"pending": 3}

        stats = integration.get_stats()
        assert stats["queue"]["pending"] == 3
        assert "cache" not in stats

    @pytest.mark.asyncio
    async def test_close_cleanup(self) -> None:
        """close should clean up all resources."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.queue = AsyncMock()
            integration.store = MagicMock()

        await integration.close()
        integration.queue.stop.assert_awaited_once()
        integration.store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_queue(self) -> None:
        """close should not fail when the background queue is disabled."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.queue = None
            integration.store = MagicMock()

        await integration.close()
        integration.store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_background_queue_no_queue(self) -> None:
        """start_background_queue should warn when no queue configured."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.queue = None
            integration.engine = MagicMock()

        # Should not raise
        await integration.start_background_queue()

    @pytest.mark.asyncio
    async def test_start_background_queue_no_engine(self) -> None:
        """start_background_queue should error when no engine configured."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(EvolutionIntegration, "__init__", lambda self, **kwargs: None):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.queue = MagicMock()
            integration.engine = None

        # Should not raise
        await integration.start_background_queue()
