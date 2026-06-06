from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus


def _make_mock_parent():
    parent = MagicMock()
    parent.config = MagicMock()
    parent._manager = AsyncMock()
    parent._spawn_child = AsyncMock()
    return parent

def _make_mock_config():
    return SubagentConfig(
        system_prompt="You are a mock agent",
        tools=("mock_tool",),
    )

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
    catalog.resolve = AsyncMock(return_value=_make_mock_config())

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
    assert result["success"] is True
    assert result["task_id"] == "test-task"

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_delegate_task_with_verifier_prompt_fallback_type(mock_run_with_verification):
    parent = _make_mock_parent()
    catalog = AsyncMock()
    def mock_resolve(type_id):
        if type_id == "coder":
            return _make_mock_config()
        return None

    catalog.resolve = AsyncMock(side_effect=mock_resolve)

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
