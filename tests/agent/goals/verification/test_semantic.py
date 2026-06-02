from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.verification.base import VerificationResult
from myrm_agent_harness.agent.goals.verification.semantic import SemanticCriterion


@pytest.fixture
def mock_goal_provider():
    provider = AsyncMock()
    provider.evaluate_semantic.return_value = VerificationResult(passed=True)
    return provider

@pytest.fixture
def mock_executor():
    with patch("myrm_agent_harness.toolkits.code_execution.executors.base.get_executor") as mock_get:
        executor = AsyncMock()
        mock_get.return_value = executor
        yield executor

@pytest.mark.asyncio
async def test_semantic_criterion_no_provider():
    criterion = SemanticCriterion(criteria="is it good?")
    result = await criterion.verify(goal_provider=None)
    assert result.passed is False
    assert "GoalProvider not injected" in result.reason

@pytest.mark.asyncio
async def test_semantic_criterion_no_target_file(mock_goal_provider):
    criterion = SemanticCriterion(criteria="is it good?")
    result = await criterion.verify(goal_provider=mock_goal_provider)

    assert result.passed is True
    mock_goal_provider.evaluate_semantic.assert_called_once()
    args = mock_goal_provider.evaluate_semantic.call_args[0]
    assert args[0] == "is it good?"
    assert "No specific file content provided" in args[1]

@pytest.mark.asyncio
async def test_semantic_criterion_with_target_file(mock_goal_provider, mock_executor):
    mock_executor.file_exists.return_value = True
    mock_executor.read_file.return_value = "def my_func(): pass"

    criterion = SemanticCriterion(criteria="is it python?", target_file="src.py")
    result = await criterion.verify(goal_provider=mock_goal_provider)

    assert result.passed is True
    mock_executor.file_exists.assert_called_once_with("src.py")
    mock_executor.read_file.assert_called_once_with("src.py")

    args = mock_goal_provider.evaluate_semantic.call_args[0]
    assert args[1] == "def my_func(): pass"

@pytest.mark.asyncio
async def test_semantic_criterion_file_not_found(mock_goal_provider, mock_executor):
    mock_executor.file_exists.return_value = False

    criterion = SemanticCriterion(criteria="is it python?", target_file="src.py")
    result = await criterion.verify(goal_provider=mock_goal_provider)

    assert result.passed is False
    assert "does not exist" in result.reason
    mock_goal_provider.evaluate_semantic.assert_not_called()

def test_semantic_criterion_from_dict():
    # Without target file
    data1 = {"type": "semantic", "criteria": "is it python?"}
    c1 = SemanticCriterion.from_dict(data1)
    assert c1.criteria == "is it python?"
    assert c1.target_file is None

    # With target file
    data2 = {"type": "semantic", "criteria": "is it python?", "target_file": "src.py"}
    c2 = SemanticCriterion.from_dict(data2)
    assert c2.target_file == "src.py"
