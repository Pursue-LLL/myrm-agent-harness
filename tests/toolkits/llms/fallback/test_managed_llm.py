"""Unit tests for ManagedLLM."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.fallback import ManagedLLM, ScenarioType


@pytest.fixture
def mock_main_llm():
    """Create mock main LLM."""
    llm = MagicMock()
    llm.agenerate = AsyncMock()
    return llm


@pytest.fixture
def mock_fallback_llm():
    """Create mock fallback LLM."""
    llm = MagicMock()
    llm.agenerate = AsyncMock()
    return llm


@pytest.mark.asyncio
async def test_managed_llm_basic_success(mock_main_llm, mock_fallback_llm):
    """Test ManagedLLM with successful main LLM call."""
    # Arrange
    expected_result = ChatResult(generations=[ChatGeneration(message=HumanMessage(content="Success"))])
    mock_main_llm.agenerate.return_value = expected_result

    managed_llm = ManagedLLM(
        main_llm=mock_main_llm,
        fallback_llm=mock_fallback_llm,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    # Act
    messages = [HumanMessage(content="Test")]
    result = await managed_llm.ainvoke(messages)

    # Assert
    assert result is not None
    mock_main_llm.agenerate.assert_called_once()
    mock_fallback_llm.agenerate.assert_not_called()


@pytest.mark.asyncio
async def test_managed_llm_failover_to_fallback(mock_main_llm, mock_fallback_llm):
    """Test ManagedLLM failover when main LLM fails."""
    # Arrange
    mock_main_llm.agenerate.side_effect = Exception("Rate limit")
    expected_result = ChatResult(generations=[ChatGeneration(message=HumanMessage(content="Fallback success"))])
    mock_fallback_llm.agenerate.return_value = expected_result

    managed_llm = ManagedLLM(
        main_llm=mock_main_llm,
        fallback_llm=mock_fallback_llm,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    # Act
    messages = [HumanMessage(content="Test")]
    result = await managed_llm.ainvoke(messages)

    # Assert
    assert result is not None
    mock_main_llm.agenerate.assert_called_once()
    mock_fallback_llm.agenerate.assert_called_once()


@pytest.mark.asyncio
async def test_managed_llm_without_fallback(mock_main_llm):
    """Test ManagedLLM without fallback LLM."""
    # Arrange
    expected_result = ChatResult(generations=[ChatGeneration(message=HumanMessage(content="Success"))])
    mock_main_llm.agenerate.return_value = expected_result

    managed_llm = ManagedLLM(
        main_llm=mock_main_llm,
        fallback_llm=None,
        main_model_name="gpt-4",
    )

    # Act
    messages = [HumanMessage(content="Test")]
    result = await managed_llm.ainvoke(messages)

    # Assert
    assert result is not None
    mock_main_llm.agenerate.assert_called_once()


@pytest.mark.asyncio
async def test_managed_llm_cooldown_behavior(mock_main_llm, mock_fallback_llm):
    """Test ManagedLLM cooldown behavior after main LLM failure."""
    # Arrange
    mock_main_llm.agenerate.side_effect = Exception("Rate limit")
    fallback_result = ChatResult(generations=[ChatGeneration(message=HumanMessage(content="Fallback"))])
    mock_fallback_llm.agenerate.return_value = fallback_result

    managed_llm = ManagedLLM(
        main_llm=mock_main_llm,
        fallback_llm=mock_fallback_llm,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    # Act - first call should failover to fallback
    messages = [HumanMessage(content="Test 1")]
    result1 = await managed_llm.ainvoke(messages)

    # Act - second call should skip main (cooldown) and use fallback directly
    result2 = await managed_llm.ainvoke(messages)

    # Assert
    assert result1 is not None
    assert result2 is not None
    # Main should be called at least once (first attempt)
    assert mock_main_llm.agenerate.call_count >= 1
    # Fallback should be called twice (both calls)
    assert mock_fallback_llm.agenerate.call_count == 2


@pytest.mark.asyncio
async def test_managed_llm_scenario_types(mock_main_llm, mock_fallback_llm):
    """Test ManagedLLM with different scenario types."""
    # Arrange
    expected_result = ChatResult(generations=[ChatGeneration(message=HumanMessage(content="Success"))])
    mock_main_llm.agenerate.return_value = expected_result

    for scenario in [ScenarioType.REALTIME, ScenarioType.BATCH, ScenarioType.BALANCED]:
        managed_llm = ManagedLLM(
            main_llm=mock_main_llm,
            fallback_llm=mock_fallback_llm,
            main_model_name="gpt-4",
            fallback_model_name="claude-3",
            scenario=scenario,
        )

        # Act
        messages = [HumanMessage(content="Test")]
        result = await managed_llm.ainvoke(messages)

        # Assert
        assert result is not None


@pytest.mark.asyncio
async def test_managed_llm_both_models_fail(mock_main_llm, mock_fallback_llm):
    """Test ManagedLLM when both main and fallback fail."""
    # Arrange
    mock_main_llm.agenerate.side_effect = Exception("Main error")
    mock_fallback_llm.agenerate.side_effect = Exception("Fallback error")

    managed_llm = ManagedLLM(
        main_llm=mock_main_llm,
        fallback_llm=mock_fallback_llm,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    # Act & Assert
    messages = [HumanMessage(content="Test")]
    with pytest.raises(Exception):
        await managed_llm.ainvoke(messages)

    mock_main_llm.agenerate.assert_called_once()
    mock_fallback_llm.agenerate.assert_called_once()


@pytest.mark.asyncio
async def test_managed_llm_preflight_guard(mock_main_llm):
    """Test ManagedLLM preflight guard blocks overflow requests."""
    import myrm_agent_harness.toolkits.llms.utils.model_utils as model_utils_mock
    import myrm_agent_harness.utils.text_utils as text_utils_mock
    import myrm_agent_harness.utils.token_estimation as token_mock
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError
    from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason

    original_get_limit = model_utils_mock.get_model_context_limit
    original_estimate = token_mock.estimate_messages_tokens
    original_count = text_utils_mock.get_token_count

    try:
        model_utils_mock.get_model_context_limit = lambda model: 1000
        token_mock.estimate_messages_tokens = lambda msgs: 900
        text_utils_mock.get_token_count = lambda text: 50

        managed_llm = ManagedLLM(
            main_llm=mock_main_llm,
            main_model_name="gpt-4",
        )
        messages = [HumanMessage(content="Test")]

        # Test 1: limit 1000, max_tokens 100. threshold = (1000-100)*0.98 = 882.
        # estimate 900 > 882. Should raise CONTEXT_OVERFLOW
        with pytest.raises(MyrmLLMError) as exc_info:
            await managed_llm._run_preflight_guard(messages, max_tokens=100)

        assert exc_info.value.error_code == FailoverReason.CONTEXT_OVERFLOW

        # Test 2: limit 1000, max_tokens 10. threshold = (1000-10)*0.98 = 970.
        # estimate 900 < 970. Should pass
        await managed_llm._run_preflight_guard(messages, max_tokens=10)

        # Test 3: test with tools. estimate 900 + tools(50) = 950.
        # limit 1000, max_tokens 10. threshold = 970.
        # 950 < 970. Should pass.
        await managed_llm._run_preflight_guard(messages, max_tokens=10, tools=[{"type": "function"}])

        # Test 4: test with tools. estimate 900 + tools(50) = 950.
        # limit 1000, max_tokens 50. threshold = (1000-50)*0.98 = 931.
        # 950 > 931. Should raise CONTEXT_OVERFLOW
        with pytest.raises(MyrmLLMError) as exc_info2:
            await managed_llm._run_preflight_guard(messages, max_tokens=50, tools=[{"type": "function"}])

        assert exc_info2.value.error_code == FailoverReason.CONTEXT_OVERFLOW

    finally:
        model_utils_mock.get_model_context_limit = original_get_limit
        token_mock.estimate_messages_tokens = original_estimate
        text_utils_mock.get_token_count = original_count

