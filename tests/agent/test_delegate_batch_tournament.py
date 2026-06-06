from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import create_batch_delegate_tasks_tool
from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import TaskRequest


def _make_mock_parent():
    parent = MagicMock()
    parent.config = MagicMock()
    parent.config.allowed_subagent_types = None
    parent.config.memory_isolation = None
    parent._manager = AsyncMock()
    parent._spawn_child = AsyncMock()
    parent.llm = AsyncMock()

    mock_response = MagicMock()
    mock_response.content = "WINNER: 1"
    parent.llm.ainvoke = AsyncMock(return_value=mock_response)

    return parent

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
@patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._run_tournament_bracket")
async def test_batch_delegate_tournament(mock_run_tournament, mock_run_parallel):
    parent = _make_mock_parent()
    catalog = AsyncMock()

    tool = create_batch_delegate_tasks_tool(parent, lambda: [], catalog)

    tasks = [
        TaskRequest(agent_type="coder", objective="Task 1"),
        TaskRequest(agent_type="coder", objective="Task 2")
    ]

    mock_payload = {
        "success": True,
        "results": [
            {"task_id": "1", "result": "A"},
            {"task_id": "2", "result": "B"}
        ]
    }
    mock_run_parallel.return_value = mock_payload
    mock_run_tournament.return_value = {"success": True, "winner": "1"}

    result = await tool.coroutine(
        tasks=tasks,
        wait=True,
        tournament=True,
        judge_criteria="Best code"
    )

    # Assert run_parallel was called with skip_merge=True
    mock_run_parallel.assert_called_once()
    assert mock_run_parallel.call_args.kwargs["skip_merge"] is True

    # Assert tournament was called
    mock_run_tournament.assert_called_once_with(parent, mock_payload["results"], "Best code")

    # Assert tasks were modified with tournament prompt
    assert "【TOURNAMENT MODE ACTIVE】" in tasks[0].objective

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
async def test_run_tournament_bracket(mock_merge):
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import _run_tournament_bracket

    parent = _make_mock_parent()
    results = [
        {"task_id": "task-1", "result": "Output A", "status": "COMPLETED", "success": True},
        {"task_id": "task-2", "result": "Output B", "status": "COMPLETED", "success": True}
    ]

    mock_merge.return_value = {"merged": True}

    final_result = await _run_tournament_bracket(parent, results, "Best code")

    assert final_result["success"] is True
    assert "tournament_winner" in final_result
    assert parent.llm.ainvoke.called
    assert mock_merge.called
