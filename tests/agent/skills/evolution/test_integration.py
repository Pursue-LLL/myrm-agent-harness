import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.hooks.types import HookEvent
from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType
from myrm_agent_harness.agent.skills.evolution.infra.integration import (
    EvolutionIntegration,
    enable_skill_evolution,
    get_global_evolution_integration,
    set_global_evolution_integration,
)


@pytest.mark.asyncio
async def test_integration_register_hooks():
    integration = EvolutionIntegration(db_path=":memory:", enable_background_queue=True)
    integration.queue = MagicMock()
    integration.queue.enqueue = AsyncMock()

    mock_registry = MagicMock()
    integration.register_hooks(mock_registry)

    # Find the registered handler for TRACE_SLICE_READY
    handler = None
    for call in mock_registry.register.call_args_list:
        if call[0][0] == HookEvent.TRACE_SLICE_READY:
            handler = call[0][1].fn
            break

    assert handler is not None

    # Test the handler
    payload = {
        "session_id": "session-123",
        "tool_call_ids": ["call_1", "call_2"],
        "agent_id": "agent-1"
    }

    await handler("TRACE_SLICE_READY", payload)

    await asyncio.sleep(0.01)
    assert integration.queue.enqueue.call_count == 1
    req = integration.queue.enqueue.call_args[0][0]

    assert req.evolution_type == EvolutionType.SLICE_EXTRACTION
    assert req.session_id == "session-123"
    assert req.tool_call_ids == ["call_1", "call_2"]
    assert req.agent_id == "agent-1"

def test_global_integration_setter_getter():
    integration = EvolutionIntegration(db_path=":memory:")
    set_global_evolution_integration(integration)
    assert get_global_evolution_integration() is integration
    set_global_evolution_integration(None)
    assert get_global_evolution_integration() is None

@pytest.mark.asyncio
async def test_integration_initialization_with_llm():
    mock_llm = MagicMock()
    with patch("myrm_agent_harness.agent.skills.evolution.infra.integration.SkillEvolutionEngine"):
        integration = EvolutionIntegration(
            db_path=":memory:",
            llm=mock_llm,
            enable_background_queue=True,
            enable_tde=True,
            enable_tool_calling=True
        )
        assert integration.engine is not None
        assert integration.queue is not None

@pytest.mark.asyncio
async def test_record_execution_success():
    from myrm_agent_harness.agent.skills.evolution.infra.tracker import SkillMetrics
    integration = EvolutionIntegration(db_path=":memory:")
    integration.tracker = MagicMock()

    mock_metrics = MagicMock(spec=SkillMetrics)
    mock_metrics.consecutive_failures = 0
    mock_metrics.should_trigger_fix.return_value = False
    integration.tracker.record_execution = AsyncMock(return_value=mock_metrics)

    integration.store = MagicMock()

    await integration.record_execution(
        skill_id="test_skill",
        success=True,
        error_message="",
        context={"task": "test"}
    )
    integration.tracker.record_execution.assert_called_once()

@pytest.mark.asyncio
async def test_record_execution_quarantine():
    from myrm_agent_harness.agent.skills.evolution.infra.tracker import SkillMetrics
    integration = EvolutionIntegration(db_path=":memory:", enable_background_queue=True)
    integration.tracker = MagicMock()
    integration.queue = MagicMock()
    integration.queue.enqueue = AsyncMock()
    integration.engine = MagicMock()

    mock_metrics = MagicMock(spec=SkillMetrics)
    mock_metrics.consecutive_failures = 3
    mock_metrics.should_trigger_fix.return_value = True
    integration.tracker.record_execution = AsyncMock(return_value=mock_metrics)

    integration.store = MagicMock()
    integration.store.deactivate_skill = AsyncMock()

    await integration.record_execution(
        skill_id="test_skill",
        success=False,
        error_message="TypeError: test",
        context={"task": "test"}
    )
    integration.store.deactivate_skill.assert_called_once()
    integration.queue.enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_get_skills_needing_fix():
    integration = EvolutionIntegration(db_path=":memory:")
    integration.tracker = MagicMock()
    integration.tracker.get_skills_needing_fix = AsyncMock(return_value=["skill1", "skill2"])

    result = await integration.get_skills_needing_fix()
    assert result == ["skill1", "skill2"]
    integration.tracker.get_skills_needing_fix.assert_called_once()

@pytest.mark.asyncio
async def test_evolve_skill():
    integration = EvolutionIntegration(db_path=":memory:")
    integration.engine = MagicMock()
    integration.engine.fix_skill = AsyncMock(return_value=MagicMock())

    result = await integration.evolve_skill("test_skill", EvolutionType.FIX, reason="error")
    assert result is not None
    integration.engine.fix_skill.assert_called_once()

@pytest.mark.asyncio
async def test_start_background_queue():
    integration = EvolutionIntegration(db_path=":memory:", enable_background_queue=True)
    integration.queue = MagicMock()
    integration.queue.start = AsyncMock()
    integration.queue.set_evolution_handler = MagicMock()
    integration.engine = MagicMock()  # Queue won't start without engine

    await integration.start_background_queue()
    integration.queue.start.assert_called_once()
    integration.queue.set_evolution_handler.assert_called_once()

@pytest.mark.asyncio
async def test_close():
    integration = EvolutionIntegration(db_path=":memory:", enable_background_queue=True)
    integration.queue = MagicMock()
    integration.queue.stop = AsyncMock()
    integration.embedding_cache = MagicMock()
    integration.embedding_cache.close = MagicMock()
    integration.store = MagicMock()
    integration.store.close = MagicMock()

    await integration.close()
    integration.queue.stop.assert_called_once()
    integration.embedding_cache.close.assert_called_once()
    integration.store.close.assert_called_once()

@pytest.mark.asyncio
async def test_get_stats():
    integration = EvolutionIntegration(db_path=":memory:", enable_background_queue=True, enable_embedding_cache=True)
    integration.metrics_tracker = MagicMock()
    integration.metrics_tracker.get_report = MagicMock(return_value={"test": "metric"})
    integration.queue = MagicMock()
    integration.queue.get_stats = MagicMock(return_value={"test": "queue"})
    integration.embedding_cache = MagicMock()
    integration.embedding_cache.get_stats = MagicMock(return_value={"test": "cache"})

    stats = integration.get_stats()
    assert stats["metrics"] == {"test": "metric"}
    assert stats["queue"] == {"test": "queue"}
    assert stats["cache"] == {"test": "cache"}

@pytest.mark.asyncio
async def test_evolve_skill_screener_blocks():
    integration = EvolutionIntegration(db_path=":memory:")
    integration.engine = MagicMock()
    integration.screener = AsyncMock()

    mock_result = MagicMock()
    mock_result.allowed = False
    mock_result.reason = "blocked"
    integration.screener.screen_request.return_value = mock_result

    result = await integration.evolve_skill("test_skill", EvolutionType.FIX)
    assert result is None
    integration.screener.screen_request.assert_called_once()


def test_enable_skill_evolution():
    with patch("myrm_agent_harness.agent.skills.evolution.infra.integration.SkillEvolutionEngine"):
        integration = enable_skill_evolution(
            db_path=":memory:",
            enable_background_queue=True
        )
        assert isinstance(integration, EvolutionIntegration)
        assert integration.queue is not None

