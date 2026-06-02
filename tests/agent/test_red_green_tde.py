"""Unit tests for TDE Red-Green testing, Intent Context, types, and integration coverage."""

import tempfile
from contextvars import copy_context
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent._skill_agent_context import get_task_intent, set_task_intent
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionRequest,
    EvolutionType,
    ExecutionAnalysis,
    SkillLineage,
    SkillMetrics,
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


class TestRecordExecutionIntentInjection:
    """Tests for EvolutionIntegration.record_execution auto-injecting task_intent."""

    @pytest.mark.asyncio
    async def test_auto_inject_task_intent(self) -> None:
        """record_execution should auto-inject task_intent from ContextVar."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )
        from myrm_agent_harness.agent.skills.evolution.infra.tracker import (
            SkillExecutionResult,
        )

        mock_store = MagicMock()
        mock_store.deactivate_skill = AsyncMock()
        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.should_trigger_fix.return_value = False
        mock_metrics.consecutive_failures = 1
        mock_tracker.record_execution = AsyncMock(return_value=mock_metrics)

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.store = mock_store
            integration.tracker = mock_tracker
            integration.engine = None
            integration.queue = None
            integration.monitor = None
            integration._bg_manager = None

        set_task_intent("Debug login page error")

        await integration.record_execution(
            skill_id="test_skill_001", success=False, error_message="Login failed"
        )

        call_args = mock_tracker.record_execution.call_args
        recorded_result: SkillExecutionResult = call_args[0][0]
        assert recorded_result.context.get("task_intent") == "Debug login page error"

    @pytest.mark.asyncio
    async def test_explicit_context_not_overridden(self) -> None:
        """If caller provides task_intent in context, it should not be overridden."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )
        from myrm_agent_harness.agent.skills.evolution.infra.tracker import (
            SkillExecutionResult,
        )

        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.should_trigger_fix.return_value = False
        mock_tracker.record_execution = AsyncMock(return_value=mock_metrics)

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.store = MagicMock()
            integration.tracker = mock_tracker
            integration.engine = None
            integration.queue = None
            integration.monitor = None
            integration._bg_manager = None

        set_task_intent("should be ignored")

        await integration.record_execution(
            skill_id="test_skill_002",
            success=True,
            context={"task_intent": "explicitly provided"},
        )

        call_args = mock_tracker.record_execution.call_args
        recorded_result: SkillExecutionResult = call_args[0][0]
        assert recorded_result.context["task_intent"] == "explicitly provided"


# ---------------------------------------------------------------------------
# Types coverage
# ---------------------------------------------------------------------------


class TestSkillMetrics:
    """Cover derived rates, recording methods, and edge cases."""

    def test_fallback_rate_zero_selections(self) -> None:
        m = SkillMetrics()
        assert m.fallback_rate == 0.0

    def test_fallback_rate_with_data(self) -> None:
        m = SkillMetrics(total_selections=10, applied_count=8)
        assert m.fallback_rate == pytest.approx(0.2)

    def test_applied_rate_zero_selections(self) -> None:
        m = SkillMetrics()
        assert m.applied_rate == 0.0

    def test_applied_rate_with_data(self) -> None:
        m = SkillMetrics(total_selections=10, applied_count=7)
        assert m.applied_rate == pytest.approx(0.7)

    def test_completion_rate_zero_applied(self) -> None:
        m = SkillMetrics()
        assert m.completion_rate == 0.0

    def test_completion_rate_with_data(self) -> None:
        m = SkillMetrics(applied_count=10, completed_count=9)
        assert m.completion_rate == pytest.approx(0.9)

    def test_effective_rate_zero_applied(self) -> None:
        m = SkillMetrics()
        assert m.effective_rate == 0.0

    def test_effective_rate_with_data(self) -> None:
        m = SkillMetrics(applied_count=10, success_count=6)
        assert m.effective_rate == pytest.approx(0.6)

    def test_success_rate_is_effective_rate(self) -> None:
        m = SkillMetrics(applied_count=4, success_count=3)
        assert m.success_rate == m.effective_rate

    def test_usage_count_is_applied_count(self) -> None:
        m = SkillMetrics(applied_count=42)
        assert m.usage_count == 42

    def test_record_applied_success(self) -> None:
        m = SkillMetrics()
        m.record_applied(success=True)
        assert m.total_selections == 1
        assert m.applied_count == 1
        assert m.completed_count == 1
        assert m.success_count == 1
        assert m.consecutive_failures == 0
        assert m.last_success_at is not None

    def test_record_applied_failure(self) -> None:
        m = SkillMetrics()
        m.record_applied(success=False)
        assert m.consecutive_failures == 1
        assert m.last_failure_at is not None

    def test_record_fallback(self) -> None:
        m = SkillMetrics()
        m.record_fallback()
        assert m.total_selections == 1
        assert m.applied_count == 0

    def test_record_success_deprecated(self) -> None:
        m = SkillMetrics()
        m.record_success()
        assert m.success_count == 1

    def test_record_failure_deprecated(self) -> None:
        m = SkillMetrics()
        m.record_failure()
        assert m.consecutive_failures == 1

    def test_should_trigger_fix_consecutive_failures(self) -> None:
        m = SkillMetrics(consecutive_failures=3)
        assert m.should_trigger_fix() is True

    def test_should_trigger_fix_low_effective_rate(self) -> None:
        m = SkillMetrics(applied_count=5, success_count=1, consecutive_failures=1)
        assert m.should_trigger_fix(threshold=0.5) is True

    def test_should_not_trigger_fix_good_rate(self) -> None:
        m = SkillMetrics(applied_count=5, success_count=4, consecutive_failures=0)
        assert m.should_trigger_fix() is False


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
            metrics=SkillMetrics(
                total_selections=10,
                applied_count=8,
                completed_count=7,
                success_count=5,
                last_success_at=datetime(2026, 1, 1),
                last_failure_at=datetime(2026, 1, 2),
                consecutive_failures=1,
            ),
        )

    def test_to_dict_roundtrip(self) -> None:
        r = self._make_record()
        d = r.to_dict()
        assert d["skill_id"] == "sk1"
        assert d["metrics"]["total_selections"] == 10
        assert d["metrics"]["last_success_at"] is not None

        r2 = SkillRecord.from_dict(d)
        assert r2.skill_id == r.skill_id
        assert r2.metrics.total_selections == r.metrics.total_selections
        assert r2.lineage.evolution_type == EvolutionType.FIX

    def test_from_dict_no_metrics(self) -> None:
        d = {
            "skill_id": "sk2",
            "name": "test",
            "description": "desc",
            "content": "# Test",
            "path": "/p",
            "lineage": {"evolution_type": "captured"},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        r = SkillRecord.from_dict(d)
        assert r.metrics.total_selections == 0


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


class TestExecutionAnalysisType:
    """Cover ExecutionAnalysis.to_dict."""

    def test_to_dict(self) -> None:
        a = ExecutionAnalysis(
            skill_id="sk1",
            task_id="t1",
            success=False,
            error_message="timeout",
            root_cause="slow API",
            task_context="Help debug",
        )
        d = a.to_dict()
        assert d["skill_id"] == "sk1"
        assert d["root_cause"] == "slow API"


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
            (skill_dir / "test_existing.py").write_text(
                "def test_old(): assert True\n", encoding="utf-8"
            )
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
        result = await executor.run_tests(
            skill_content='"""Skill."""', test_code=test_code, skill_name="test_skill"
        )
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
        integration = EvolutionIntegration(
            db_path=db_path, llm=mock_llm, enable_tde=True, enable_tool_calling=True
        )

        assert integration.db_path == db_path
        assert integration.store is not None
        assert integration.tracker is not None
        assert integration.analyzer is not None
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

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
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

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.engine = AsyncMock()
            integration.engine.fix_skill = AsyncMock(return_value="fixed")
            integration.screener = None

        result = await integration.evolve_skill(
            "sk1", EvolutionType.FIX, reason="crash"
        )
        assert result == "fixed"
        integration.engine.fix_skill.assert_awaited_once_with("sk1", "crash")

    @pytest.mark.asyncio
    async def test_evolve_skill_derived(self) -> None:
        """evolve_skill with DERIVED type should call engine.derive_skill_simple."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.engine = AsyncMock()
            integration.engine.derive_skill_simple = AsyncMock(return_value="derived")
            integration.screener = None

        result = await integration.evolve_skill(
            "sk1", EvolutionType.DERIVED, user_feedback="faster"
        )
        assert result == "derived"

    @pytest.mark.asyncio
    async def test_evolve_skill_captured(self) -> None:
        """evolve_skill with CAPTURED type should call engine.capture_skill_simple."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.engine = AsyncMock()
            integration.engine.capture_skill_simple = AsyncMock(return_value="captured")
            integration.screener = None

        result = await integration.evolve_skill(
            "sk1",
            EvolutionType.CAPTURED,
            repeated_commands=["ls", "ls"],
            user_confirmed=True,
        )
        assert result == "captured"

    @pytest.mark.asyncio
    async def test_record_execution_deterministic_error_quarantine(self) -> None:
        """record_execution should trigger 1-strike quarantine for deterministic errors."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.should_trigger_fix.return_value = False
        mock_metrics.consecutive_failures = 1
        mock_tracker.record_execution = AsyncMock(return_value=mock_metrics)

        mock_engine = AsyncMock()
        mock_engine.fix_skill = AsyncMock()

        mock_store = MagicMock()
        mock_store.deactivate_skill = AsyncMock()

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.store = mock_store
            integration.tracker = mock_tracker
            integration.engine = mock_engine
            integration.queue = None

        await integration.record_execution(
            skill_id="broken",
            success=False,
            error_message="SyntaxError: invalid syntax",
        )

        mock_store.deactivate_skill.assert_called_once_with("broken")
        mock_engine.fix_skill.assert_called_once_with(
            "broken", "SyntaxError: invalid syntax"
        )

    @pytest.mark.asyncio
    async def test_record_execution_triggers_fix_immediate(self) -> None:
        """record_execution should trigger immediate fix when no queue and should_trigger_fix=True."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.should_trigger_fix.return_value = True
        mock_metrics.success_rate = 0.1
        mock_metrics.consecutive_failures = 5
        mock_tracker.record_execution = AsyncMock(return_value=mock_metrics)

        mock_engine = AsyncMock()
        mock_engine.fix_skill = AsyncMock()

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.store = MagicMock()
            integration.store.deactivate_skill = AsyncMock()
            integration.tracker = mock_tracker
            integration.engine = mock_engine
            integration.queue = None

        await integration.record_execution(
            skill_id="broken", success=False, error_message="crash"
        )
        mock_engine.fix_skill.assert_awaited_once_with("broken", "crash")

    @pytest.mark.asyncio
    async def test_record_execution_enqueues_when_queue_enabled(self) -> None:
        """record_execution should enqueue when queue is enabled and should_trigger_fix=True."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.should_trigger_fix.return_value = True
        mock_metrics.success_rate = 0.2
        mock_metrics.consecutive_failures = 2
        mock_tracker.record_execution = AsyncMock(return_value=mock_metrics)

        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock()

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.store = MagicMock()
            integration.tracker = mock_tracker
            integration.engine = MagicMock()
            integration.queue = mock_queue

        await integration.record_execution(
            skill_id="flaky", success=False, error_message="fail"
        )
        mock_queue.enqueue.assert_awaited_once()

    def test_get_stats_minimal(self) -> None:
        """get_stats should return metrics even with no queue or cache."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.metrics_tracker = MagicMock()
            integration.metrics_tracker.get_report.return_value = {"total": 0}
            integration.queue = None
            integration.embedding_cache = None

        stats = integration.get_stats()
        assert "metrics" in stats
        assert stats["metrics"]["total"] == 0

    def test_get_stats_with_queue_and_cache(self) -> None:
        """get_stats should include queue and cache stats when enabled."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.metrics_tracker = MagicMock()
            integration.metrics_tracker.get_report.return_value = {}
            integration.queue = MagicMock()
            integration.queue.get_stats.return_value = {"pending": 3}
            integration.embedding_cache = MagicMock()
            integration.embedding_cache.get_stats.return_value = {"hits": 10}

        stats = integration.get_stats()
        assert stats["queue"]["pending"] == 3
        assert stats["cache"]["hits"] == 10

    @pytest.mark.asyncio
    async def test_close_cleanup(self) -> None:
        """close should clean up all resources."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.queue = AsyncMock()
            integration.embedding_cache = MagicMock()
            integration.store = MagicMock()

        await integration.close()
        integration.queue.stop.assert_awaited_once()
        integration.embedding_cache.close.assert_called_once()
        integration.store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_optional_resources(self) -> None:
        """close should not fail when optional resources are None."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.queue = None
            integration.embedding_cache = None
            integration.store = MagicMock()

        await integration.close()
        integration.store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_skills_needing_fix(self) -> None:
        """get_skills_needing_fix should delegate to tracker."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.tracker = MagicMock()
            integration.tracker.get_skills_needing_fix = AsyncMock(return_value=["sk1"])

        result = await integration.get_skills_needing_fix()
        assert result == ["sk1"]

    @pytest.mark.asyncio
    async def test_start_background_queue_no_queue(self) -> None:
        """start_background_queue should warn when no queue configured."""
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
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

        with patch.object(
            EvolutionIntegration, "__init__", lambda self, **kwargs: None
        ):
            integration = EvolutionIntegration.__new__(EvolutionIntegration)
            integration.queue = MagicMock()
            integration.engine = None

        # Should not raise
        await integration.start_background_queue()
