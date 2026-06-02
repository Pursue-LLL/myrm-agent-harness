"""Tests for multi-level fallback support in ManagedLLM."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.fallback import FallbackModel, ManagedLLM


@pytest.mark.asyncio
async def test_multi_level_fallback_3_models():
    """Test 3-level fallback chain."""
    # Create mock LLMs
    main_llm = MagicMock()
    fallback1_llm = MagicMock()
    fallback2_llm = MagicMock()

    # Main LLM fails
    main_llm.agenerate = AsyncMock(side_effect=Exception("Main failed"))

    # Fallback1 LLM fails
    fallback1_llm.agenerate = AsyncMock(side_effect=Exception("Fallback1 failed"))

    # Fallback2 LLM succeeds
    fallback2_llm.agenerate = AsyncMock(
        return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content="fallback2 response"))])
    )

    # Create ManagedLLM with 3-level fallback
    managed_llm = ManagedLLM(
        main_llm=main_llm,
        fallback_models=[
            FallbackModel(llm=fallback1_llm, name="fallback1", cost=0.3, quality=0.75),
            FallbackModel(llm=fallback2_llm, name="fallback2", cost=0.1, quality=0.6),
        ],
        main_model_name="main",
    )

    # Execute
    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    # Verify result came from fallback2
    assert result.content == "fallback2 response"

    # Verify all LLMs were tried
    assert main_llm.agenerate.call_count == 1
    assert fallback1_llm.agenerate.call_count == 1
    assert fallback2_llm.agenerate.call_count == 1


@pytest.mark.asyncio
async def test_multi_level_fallback_4_models():
    """Test 4-level fallback chain."""
    # Create mock LLMs
    llms = [MagicMock() for _ in range(4)]

    # First 3 fail, last succeeds
    for i in range(3):
        llms[i].agenerate = AsyncMock(side_effect=Exception(f"Model {i} failed"))
    llms[3].agenerate = AsyncMock(
        return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content="final fallback"))])
    )

    # Create ManagedLLM with 4-level fallback (main + 3 fallbacks)
    managed_llm = ManagedLLM(
        main_llm=llms[0],
        fallback_models=[
            FallbackModel(llm=llms[i + 1], name=f"fallback{i}", cost=0.5 - i * 0.1, quality=0.8 - i * 0.1)
            for i in range(3)
        ],
        main_model_name="main",
    )

    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    # Verify result came from last fallback
    assert result.content == "final fallback"

    # Verify all LLMs were tried
    for llm in llms:
        assert llm.agenerate.call_count == 1


@pytest.mark.asyncio
async def test_multi_level_fallback_first_succeeds():
    """Test that execution stops at first successful model."""
    llms = [MagicMock() for _ in range(4)]

    # All models configured to succeed
    for i, llm in enumerate(llms):
        llm.agenerate = AsyncMock(
            return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"response_{i}"))])
        )

    managed_llm = ManagedLLM(
        main_llm=llms[0],
        fallback_models=[
            FallbackModel(llm=llms[i], name=f"fallback{i - 1}", cost=0.5, quality=0.7) for i in range(1, 4)
        ],
        main_model_name="main",
    )

    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    # Should use main model only
    assert result.content == "response_0"
    assert llms[0].agenerate.call_count == 1

    # Other models should not be called
    for llm in llms[1:]:
        assert llm.agenerate.call_count == 0


@pytest.mark.asyncio
async def test_backward_compatible_2_level():
    """Test backward compatibility with 2-level fallback."""
    main_llm = MagicMock()
    fallback_llm = MagicMock()

    main_llm.agenerate = AsyncMock(side_effect=Exception("Main failed"))
    fallback_llm.agenerate = AsyncMock(
        return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content="fallback"))])
    )

    # Use old API (fallback_llm parameter)
    managed_llm = ManagedLLM(
        main_llm=main_llm,
        fallback_llm=fallback_llm,
        main_model_name="main",
        fallback_model_name="fallback",
    )

    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    assert result.content == "fallback"


@pytest.mark.asyncio
async def test_mutually_exclusive_parameters():
    """Test that fallback_llm and fallback_models are mutually exclusive."""
    main_llm = MagicMock()
    fallback_llm = MagicMock()

    with pytest.raises(ValueError, match="Cannot specify both"):
        ManagedLLM(
            main_llm=main_llm,
            fallback_llm=fallback_llm,
            fallback_models=[FallbackModel(llm=MagicMock(), name="fb")],
        )


@pytest.mark.asyncio
async def test_identifying_params_multi_level():
    """Test _identifying_params returns all fallback models."""
    main_llm = MagicMock()
    fallback_llms = [MagicMock() for _ in range(3)]

    managed_llm = ManagedLLM(
        main_llm=main_llm,
        fallback_models=[FallbackModel(llm=fallback_llms[i], name=f"fb{i}", cost=0.5, quality=0.7) for i in range(3)],
        main_model_name="main",
    )

    params = managed_llm._identifying_params

    assert params["main_model"] == "main"
    assert "fb0" in params["fallback_models"]
    assert "fb1" in params["fallback_models"]
    assert "fb2" in params["fallback_models"]
    assert len(params["fallback_models"]) == 3
