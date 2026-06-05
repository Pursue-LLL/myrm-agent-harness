import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus

def _make_mock_parent():
    parent = MagicMock()
    parent.config = MagicMock()
    parent.config.allowed_subagent_types = None
    parent.config.memory_isolation = None
    parent._manager = AsyncMock()
    parent._spawn_child = AsyncMock()
    return parent

@pytest.mark.asyncio
async def test_delegate_task_with_verifier_prompt_and_wait_false():
    parent = _make_mock_parent()
    catalog = AsyncMock()
    tool = create_delegate_task_tool(parent, lambda: [], catalog)
    
    result = await tool.coroutine(
        agent_type="coder",
        objective="Write a function",
        wait=False,
        verifier_prompt="Verify it",
    )
    
    assert result["success"] is False
    assert "Adversarial verification requires wait=True" in result["error"]

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_delegate_task_with_verifier_prompt_and_wait_true(mock_run_with_verification):
    parent = _make_mock_parent()
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=MagicMock())
    
    tool = create_delegate_task_tool(parent, lambda: [], catalog)
    
    mock_result = SubAgentResult(
        success=True,
        task_id="test-task",
        agent_type="coder",
        result="Done",
        completed_at=123.0,
        status=SubAgentStatus.COMPLETED
    )
    mock_run_with_verification.return_value = mock_result
    
    result = await tool.coroutine(
        agent_type="coder",
        objective="Write a function",
        wait=True,
        verifier_prompt="Verify it",
        verifier_agent_type="verifier",
        max_verification_rounds=3,
    )
    
    assert catalog.resolve.called
    mock_run_with_verification.assert_called_once()
    kwargs = mock_run_with_verification.call_args.kwargs
    assert kwargs["worker_type"] == "coder"
    assert kwargs["verifier_type"] == "verifier"
    assert kwargs["max_rounds"] == 3
    assert kwargs["verifier_task_template"] == "Verify it"
    assert result == mock_result.to_dict()

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_delegate_task_with_verifier_prompt_fallback_type(mock_run_with_verification):
    parent = _make_mock_parent()
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=None)
    
    tool = create_delegate_task_tool(parent, lambda: [], catalog)
    
    mock_result = SubAgentResult(
        success=True,
        task_id="test-task",
        agent_type="coder",
        result="Done",
        completed_at=123.0,
        status=SubAgentStatus.COMPLETED
    )
    mock_run_with_verification.return_value = mock_result
    
    result = await tool.coroutine(
        agent_type="coder",
        objective="Write a function",
        wait=True,
        verifier_prompt="Verify it",
        verifier_agent_type="unknown-verifier",
    )
    
    assert catalog.resolve.called
    mock_run_with_verification.assert_called_once()
    kwargs = mock_run_with_verification.call_args.kwargs
    assert kwargs["verifier_type"] == "coder"
