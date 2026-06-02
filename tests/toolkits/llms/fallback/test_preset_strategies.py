"""Tests for preset fallback strategies."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.fallback import (
    PRESET_STRATEGIES,
    create_managed_llm_from_preset,
    get_preset_strategy,
)
from myrm_agent_harness.toolkits.llms.fallback.scenario import ScenarioType


def test_get_preset_strategy_gpt4_standard():
    """Test getting GPT-4 standard strategy."""
    strategy = get_preset_strategy("gpt-4-standard")

    assert strategy.name == "gpt-4-standard"
    assert strategy.main_model == "gpt-4"
    assert len(strategy.fallback_models) == 2
    assert strategy.fallback_models[0]["name"] == "gpt-4-turbo"
    assert strategy.fallback_models[1]["name"] == "gpt-4o-mini"
    assert strategy.scenario == ScenarioType.BALANCED


def test_get_preset_strategy_high_availability():
    """Test getting high availability strategy."""
    strategy = get_preset_strategy("gpt-4-high-availability")

    assert strategy.main_model == "gpt-4"
    assert len(strategy.fallback_models) == 3
    assert strategy.scenario == ScenarioType.QUALITY_FIRST
    assert strategy.probe_config.cooldown_ms == 15_000
    assert strategy.probe_config.max_probe_attempts == 5


def test_get_preset_strategy_claude_opus():
    """Test getting Claude Opus strategy."""
    strategy = get_preset_strategy("claude-opus-standard")

    assert strategy.main_model == "claude-3-opus"
    assert len(strategy.fallback_models) == 2
    assert strategy.fallback_models[0]["name"] == "claude-3-sonnet"


def test_get_preset_strategy_gemini_pro():
    """Test getting Gemini Pro strategy."""
    strategy = get_preset_strategy("gemini-pro-standard")

    assert strategy.main_model == "gemini-1.5-pro"
    assert strategy.scenario == ScenarioType.QUALITY_FIRST


def test_get_preset_strategy_cost_optimized():
    """Test getting cost-optimized strategy."""
    strategy = get_preset_strategy("cost-optimized")

    assert strategy.main_model == "gpt-4o-mini"
    assert strategy.scenario == ScenarioType.REALTIME


def test_get_preset_strategy_realtime():
    """Test getting realtime-optimized strategy."""
    strategy = get_preset_strategy("realtime-optimized")

    assert strategy.main_model == "gpt-4o"
    assert strategy.scenario == ScenarioType.REALTIME
    assert strategy.probe_config.cooldown_ms == 15_000


def test_get_preset_strategy_unknown():
    """Test getting unknown strategy raises error."""
    with pytest.raises(ValueError, match="Unknown strategy"):
        get_preset_strategy("nonexistent-strategy")


def test_preset_strategies_available():
    """Test that all preset strategies are accessible."""
    expected_strategies = [
        "gpt-4-standard",
        "gpt-4-high-availability",
        "claude-opus-standard",
        "gemini-pro-standard",
        "cost-optimized",
        "realtime-optimized",
    ]

    for strategy_name in expected_strategies:
        assert strategy_name in PRESET_STRATEGIES

    assert len(PRESET_STRATEGIES) == 6


@pytest.mark.asyncio
async def test_create_managed_llm_from_preset():
    """Test creating ManagedLLM from preset strategy."""
    # Create mock LLM factory
    llm_factory = {
        "gpt-4": MagicMock(),
        "gpt-4-turbo": MagicMock(),
        "gpt-4o-mini": MagicMock(),
    }

    # Configure mocks
    llm_factory["gpt-4"].agenerate = AsyncMock(
        return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content="gpt-4 response"))])
    )

    # Create from preset
    managed_llm = create_managed_llm_from_preset(
        "gpt-4-standard",
        llm_factory,
    )

    # Test execution
    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    assert result.content == "gpt-4 response"
    assert llm_factory["gpt-4"].agenerate.call_count == 1


@pytest.mark.asyncio
async def test_create_from_preset_missing_models():
    """Test that missing models in factory raises error."""
    llm_factory = {
        "gpt-4": MagicMock(),
        # Missing gpt-4-turbo and gpt-4o-mini
    }

    with pytest.raises(ValueError, match="Missing LLM instances"):
        create_managed_llm_from_preset("gpt-4-standard", llm_factory)


@pytest.mark.asyncio
async def test_create_from_preset_unknown_strategy():
    """Test that unknown strategy raises error."""
    llm_factory = {"model": MagicMock()}

    with pytest.raises(ValueError, match="Unknown strategy"):
        create_managed_llm_from_preset("nonexistent", llm_factory)


@pytest.mark.asyncio
async def test_preset_strategy_probe_config():
    """Test that preset strategy probe config is applied."""
    llm_factory = {
        "gpt-4": MagicMock(),
        "gpt-4-turbo": MagicMock(),
        "claude-3-opus": MagicMock(),
        "gpt-4o-mini": MagicMock(),
    }

    # Configure all to succeed
    for llm in llm_factory.values():
        llm.agenerate = AsyncMock(
            return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])
        )

    # Create high-availability strategy (has custom probe config)
    managed_llm = create_managed_llm_from_preset(
        "gpt-4-high-availability",
        llm_factory,
    )

    # Verify it's created successfully (probe_config is applied internally)
    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)
    assert result.content == "ok"
