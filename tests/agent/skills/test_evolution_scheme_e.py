"""Unit tests for Evolution engine and tool config features.

Tests cover:
1. SkillEvolutionEngine core API (fix/derive/capture)
2. EvolutionToolConfig validation (limits, warnings)
3. ExecutorContextManager (background_queue scenario)
4. EvolutionMetricsTracker
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine
from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore
from myrm_agent_harness.agent.skills.evolution.execution.executor_context import ExecutorContextManager
from myrm_agent_harness.agent.skills.evolution.execution.tool_selector import EvolutionToolConfig
from myrm_agent_harness.agent.skills.evolution.infra.metrics import EvolutionMetricsTracker


class TestSkillEvolutionEngineInit:
    """Test engine initialization and basic invariants."""

    def test_init_with_defaults(self):
        store = MagicMock(spec=SkillStore)
        engine = SkillEvolutionEngine(store)

        assert engine._store is store
        assert engine._llm is None
        assert engine._num_variants == 3

    def test_init_with_custom_params(self):
        store = MagicMock(spec=SkillStore)
        llm = MagicMock()
        engine = SkillEvolutionEngine(store, llm, max_concurrent_evolutions=2, num_variants_per_evolution=5)

        assert engine._llm is llm
        assert engine._num_variants == 5

    def test_init_without_event_log_backend(self):
        store = MagicMock(spec=SkillStore)
        engine = SkillEvolutionEngine(store)
        assert engine._trace_analyzer is None


class TestFixSkill:
    """Test fix_skill method."""

    @pytest.mark.asyncio
    async def test_fix_nonexistent_skill_returns_none(self):
        store = MagicMock(spec=SkillStore)
        store.get_skill.return_value = None
        engine = SkillEvolutionEngine(store)

        result = await engine.fix_skill("nonexistent", "error msg")
        assert result is None

    @pytest.mark.asyncio
    async def test_fix_locked_skill_returns_none(self):
        store = MagicMock(spec=SkillStore)
        locked_skill = MagicMock(spec=SkillRecord)
        locked_skill.evolution_locked = True
        locked_skill.name = "locked_skill"
        store.get_skill.return_value = locked_skill
        engine = SkillEvolutionEngine(store)

        result = await engine.fix_skill("locked", "error")
        assert result is None

    @pytest.mark.asyncio
    async def test_fix_skill_no_variants_returns_none(self):
        store = MagicMock(spec=SkillStore)
        skill = MagicMock(spec=SkillRecord)
        skill.evolution_locked = False
        skill.name = "test_skill"
        skill.skill_id = "test"
        skill.content = "old content"
        store.get_skill.return_value = skill
        store.get_evolution_constraints.return_value = []
        store.search_skills.return_value = []

        engine = SkillEvolutionEngine(store)
        engine._variant_generator = MagicMock()
        engine._variant_generator.generate_variants = AsyncMock(return_value=[])

        result = await engine.fix_skill("test", "error")
        assert result is None


class TestDeriveSkill:
    """Test derive_skill_simple method."""

    @pytest.mark.asyncio
    async def test_derive_nonexistent_returns_none(self):
        store = MagicMock(spec=SkillStore)
        store.get_skill.return_value = None
        engine = SkillEvolutionEngine(store)

        result = await engine.derive_skill_simple("nope", "feedback")
        assert result is None

    @pytest.mark.asyncio
    async def test_derive_locked_returns_none(self):
        store = MagicMock(spec=SkillStore)
        locked = MagicMock(spec=SkillRecord)
        locked.evolution_locked = True
        locked.name = "locked"
        store.get_skill.return_value = locked
        engine = SkillEvolutionEngine(store)

        result = await engine.derive_skill_simple("locked", "optimize")
        assert result is None


class TestDeriveSkillSimple:
    """Test derive_skill_simple method."""

    @pytest.mark.asyncio
    async def test_derive_nonexistent_skill_returns_none(self):
        store = MagicMock(spec=SkillStore)
        store.get_skill.return_value = None
        engine = SkillEvolutionEngine(store)

        result = await engine.derive_skill_simple("nonexistent", "improve it")
        assert result is None

    @pytest.mark.asyncio
    async def test_derive_calls_store(self):
        store = MagicMock(spec=SkillStore)
        store.get_skill.return_value = None
        engine = SkillEvolutionEngine(store)

        result = await engine.derive_skill_simple("missing_id", "feedback")
        assert result is None
        store.get_skill.assert_called_once_with("missing_id")


class TestEvolveMultipleConcurrent:
    """Test evolve_multiple_concurrent."""

    @pytest.mark.asyncio
    async def test_empty_requests_returns_empty(self):
        store = MagicMock(spec=SkillStore)
        engine = SkillEvolutionEngine(store)

        results = await engine.evolve_multiple_concurrent([])
        assert results == []


class TestConfigValidation:
    """Test EvolutionToolConfig validation logic."""

    def test_default_tool_limits_set(self):
        config = EvolutionToolConfig(max_tool_rounds=3)

        assert config.tool_call_limits is not None
        assert config.tool_call_limits["web_search"] == 3
        assert config.tool_call_limits["file_read"] == 15
        assert config.tool_call_limits["glob"] == 5

    def test_max_tool_rounds_minimum_enforced(self, caplog):
        with caplog.at_level(logging.WARNING):
            config = EvolutionToolConfig(max_tool_rounds=0)

        assert config.max_tool_rounds == 1
        assert "max_tool_rounds < 1, setting to 1" in caplog.text

    def test_max_tool_rounds_excessive_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            config = EvolutionToolConfig(max_tool_rounds=15)

        assert config.max_tool_rounds == 15
        assert "max_tool_rounds > 10, this may be excessive" in caplog.text

    def test_max_tool_rounds_cost_warning(self, caplog):
        with caplog.at_level(logging.INFO):
            config = EvolutionToolConfig(max_tool_rounds=7)

        assert config.max_tool_rounds == 7
        assert "cost implications" in caplog.text

    def test_summarization_threshold_minimum_enforced(self, caplog):
        with caplog.at_level(logging.WARNING):
            config = EvolutionToolConfig(max_tool_rounds=3, result_summarization_threshold=500)

        assert config.result_summarization_threshold == 1000
        assert "too small, setting to 1000" in caplog.text

    def test_tool_limits_consistency_check(self, caplog):
        with caplog.at_level(logging.WARNING):
            EvolutionToolConfig(max_tool_rounds=20, tool_call_limits={"web_search": 1, "file_read": 2})

        assert "may hit limits before reaching max rounds" in caplog.text


class TestExecutorContextManager:
    """Test ExecutorContextManager (background_queue scenario)."""

    @pytest.mark.asyncio
    async def test_executor_context_in_sync_task(self):
        mock_executor = MagicMock()

        async with ExecutorContextManager(mock_executor):
            pass

    @pytest.mark.asyncio
    async def test_executor_context_in_background_task(self):
        mock_executor = MagicMock()

        async def background_task():
            await asyncio.sleep(0.01)
            return "done"

        async with ExecutorContextManager(mock_executor):
            task = asyncio.create_task(background_task())
            result = await task

        assert result == "done"

    @pytest.mark.asyncio
    async def test_executor_context_cleanup(self):
        mock_executor = MagicMock()

        async with ExecutorContextManager(mock_executor):
            pass


class TestMetricsIntegration:
    """Test that metrics are properly recorded."""

    def test_record_tool_call_success(self):
        tracker = EvolutionMetricsTracker()

        tracker.record_tool_call("file_read", elapsed_time=0.5, success=True)

        metrics = tracker.get_metrics()
        assert metrics.tool_call_count == 1
        assert metrics.tool_call_time == 0.5
        assert metrics.tool_errors == 0

    def test_record_tool_call_failure(self):
        tracker = EvolutionMetricsTracker()

        tracker.record_tool_call("web_search", elapsed_time=1.2, success=False)

        metrics = tracker.get_metrics()
        assert metrics.tool_call_count == 1
        assert metrics.tool_call_time == 1.2
        assert metrics.tool_errors == 1

    def test_record_summarization(self):
        tracker = EvolutionMetricsTracker()

        tracker.record_summarization(original_length=10000, summarized_length=1000, elapsed_time=0.3)

        metrics = tracker.get_metrics()
        assert metrics.summarization_count == 1
        assert metrics.summarization_time == 0.3
        assert metrics.token_saved == 2250

    def test_metrics_report_includes_new_fields(self):
        tracker = EvolutionMetricsTracker()

        tracker.record_tool_call("file_read", 0.5, True)
        tracker.record_summarization(5000, 500, 0.2)

        report = tracker.get_report()

        assert "tool_usage" in report
        assert report["tool_usage"]["total_calls"] == 1
        assert "summarization" in report
        assert report["summarization"]["count"] == 1
        assert report["summarization"]["token_saved"] == 1125
