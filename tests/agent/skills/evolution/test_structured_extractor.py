from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor import (
    SkillCaptureResult,
    StructuredExtractor,
)


@pytest.mark.asyncio
async def test_structured_extractor_success():
    mock_llm = MagicMock()
    mock_structured_llm = MagicMock()

    mock_result = SkillCaptureResult(
        is_general=True,
        confidence=0.9,
        safety_analysis="Safe",
        name="test-skill",
        content="## Instructions\n1. Do something.",
    )

    mock_structured_llm.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm.with_structured_output.return_value = mock_structured_llm

    extractor = StructuredExtractor(mock_llm)
    result = await extractor.extract_from_trajectory("User: fix it. Assistant: fixed.")

    assert result is not None
    assert result.name == "test-skill"
    assert result.is_general is True
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_structured_extractor_wrong_type():
    mock_llm = MagicMock()
    mock_structured_llm = MagicMock()

    # Return string instead of SkillCaptureResult
    mock_structured_llm.ainvoke = AsyncMock(return_value="Not a pydantic object")
    mock_llm.with_structured_output.return_value = mock_structured_llm

    extractor = StructuredExtractor(mock_llm)
    result = await extractor.extract_from_trajectory("trajectory")

    assert result is None


@pytest.mark.asyncio
async def test_structured_extractor_exception():
    mock_llm = MagicMock()
    mock_structured_llm = MagicMock()

    mock_structured_llm.ainvoke = AsyncMock(side_effect=Exception("API Error"))
    mock_llm.with_structured_output.return_value = mock_structured_llm

    extractor = StructuredExtractor(mock_llm)
    result = await extractor.extract_from_trajectory("trajectory")

    assert result is None
