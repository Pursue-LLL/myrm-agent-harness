from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.skills.evolution.safety.judge import EvolutionJudge


@pytest.fixture
def mock_llm():
    return AsyncMock()

@pytest.mark.asyncio
async def test_evaluate_no_llm():
    judge = EvolutionJudge(judge_llm=None)
    result = await judge.evaluate("old", "new", "error")
    assert result.confidence == 0.5
    assert "No judge LLM configured" in result.reason

@pytest.mark.asyncio
async def test_evaluate_success(mock_llm):
    mock_response = MagicMock()
    mock_response.content = "Confidence: 0.95\nReasoning: Looks good."
    mock_llm.ainvoke.return_value = mock_response

    judge = EvolutionJudge(judge_llm=mock_llm)
    result = await judge.evaluate("old code", "new code", "ValueError")

    assert result.confidence == 0.95
    assert "Confidence: 0.95\nReasoning: Looks good." in result.reason
    mock_llm.ainvoke.assert_called_once()

    # check prompt structure
    call_args = mock_llm.ainvoke.call_args[0][0]
    assert len(call_args) == 1
    assert isinstance(call_args[0], HumanMessage)
    assert "ValueError" in call_args[0].content
    assert "old code" in call_args[0].content
    assert "new code" in call_args[0].content

@pytest.mark.asyncio
async def test_evaluate_exception(mock_llm):
    mock_llm.ainvoke.side_effect = Exception("API Error")

    judge = EvolutionJudge(judge_llm=mock_llm)
    result = await judge.evaluate("old", "new", "error")

    assert result.confidence == 0.5
    assert "LLM judge evaluation failed" in result.reason
    assert "API Error" in result.reason

def test_parse_llm_response_float():
    judge = EvolutionJudge()
    content = "Confidence: 0.85\nReason: nice."
    conf, reason = judge._parse_llm_response(content)
    assert conf == 0.85
    assert reason == content

def test_parse_llm_response_percentage():
    judge = EvolutionJudge()
    content = "Confidence: 90\nReason: nice."
    conf, reason = judge._parse_llm_response(content)
    assert conf == 0.9
    assert reason == content

def test_parse_llm_response_no_match():
    judge = EvolutionJudge()
    content = "I think it is a good fix, probably."
    conf, reason = judge._parse_llm_response(content)
    assert conf == 0.5 # default
    assert reason == content

def test_parse_llm_response_invalid_value():
    judge = EvolutionJudge()
    content = "Confidence: high\nReason: nice."
    conf, reason = judge._parse_llm_response(content)
    assert conf == 0.5 # default
    assert reason == content

def test_parse_llm_response_clamp_max():
    judge = EvolutionJudge()
    content = "Confidence: 1.5\nReason: nice."
    # 1.5 is > 1.0, so it will divide by 100 -> 0.015
    conf, reason = judge._parse_llm_response(content)
    assert conf == 0.015
    assert reason == content

def test_parse_llm_response_clamp_max_real():
    judge = EvolutionJudge()
    # what if someone says 105%?
    content = "Confidence: 105\nReason: nice."
    conf, reason = judge._parse_llm_response(content)
    # 105 / 100 = 1.05. Clamp max 1.0 -> 1.0
    assert conf == 1.0
    assert reason == content

def test_parse_llm_response_clamp_min():
    judge = EvolutionJudge()
    content = "Confidence: -0.5\nReason: nice."
    # negative not matched by regex usually, but let's test if it did (it won't match '-' in `([0-9.]+)`)
    # let's mock it
    content = "Confidence: 0.0\nReason: nice."
    conf, reason = judge._parse_llm_response(content)
    assert conf == 0.0
    assert reason == content
