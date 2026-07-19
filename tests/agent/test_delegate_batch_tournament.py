from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
    TaskRequest,
    create_delegate_task_tool,
)


def _make_mock_parent():
    parent = MagicMock()
    parent.config = MagicMock()
    parent.config.allowed_subagent_types = None
    parent.config.memory_isolation = None
    parent._manager = AsyncMock()
    parent._spawn_child = AsyncMock()
    parent.llm = AsyncMock()
    parent._last_context = {"session_id": "chat_test-session"}

    mock_response = MagicMock()
    mock_response.content = "WINNER: 1"
    parent.llm.ainvoke = AsyncMock(return_value=mock_response)

    return parent


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
@patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._run_tournament_bracket")
@patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
async def test_delegate_task_batch_tournament(mock_estimate_cost, mock_run_tournament, mock_run_parallel):
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _BatchBudgetAdmission

    mock_estimate_cost.return_value = _BatchBudgetAdmission(
        status="unavailable",
        reason="test_skip",
    )
    parent = _make_mock_parent()
    catalog = AsyncMock()

    delegate_tool = create_delegate_task_tool(parent, lambda: [], catalog)

    tasks = [
        TaskRequest(agent_type="coder", objective="Task 1"),
        TaskRequest(agent_type="coder", objective="Task 2"),
    ]

    mock_payload = {
        "success": True,
        "results": [
            {"task_id": "1", "result": "A"},
            {"task_id": "2", "result": "B"},
        ],
    }
    mock_run_parallel.return_value = mock_payload
    mock_run_tournament.return_value = {"success": True, "winner": "1"}

    result = await delegate_tool.ainvoke(
        {
            "mode": "batch",
            "tasks": tasks,
            "wait": True,
            "tournament": True,
            "judge_criteria": "Best code",
        }
    )

    assert result["success"] is True

    mock_run_parallel.assert_called_once()
    assert mock_run_parallel.call_args.kwargs["skip_merge"] is True

    mock_run_tournament.assert_called_once_with(parent, mock_payload["results"], "Best code")

    assert "【TOURNAMENT MODE ACTIVE】" in tasks[0].objective


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
async def test_run_tournament_bracket(mock_merge):
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import _run_tournament_bracket

    parent = _make_mock_parent()
    results = [
        {"task_id": "task-1", "result": "Output A", "status": "COMPLETED", "success": True},
        {"task_id": "task-2", "result": "Output B", "status": "COMPLETED", "success": True},
    ]

    mock_merge.return_value = {"merged": True}

    final_result = await _run_tournament_bracket(parent, results, "Best code")

    assert final_result["success"] is True
    assert "tournament_winner" in final_result
    assert parent.llm.ainvoke.called
    assert mock_merge.called
