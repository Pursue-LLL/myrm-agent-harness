"""Unit and integration tests for A2A outbound client and delegation tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from myrm_agent_harness.toolkits.a2a.client import (
    A2AClient,
    A2AClientError,
    A2ARpcError,
    A2ASSRFBlockedError,
)
from myrm_agent_harness.toolkits.a2a.tools import (
    FanoutMode,
    execute_a2a_call,
    execute_a2a_orchestrate,
)
from myrm_agent_harness.toolkits.a2a.types import (
    A2ATask,
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcResponse,
    TaskArtifact,
    TaskMessage,
    TaskRole,
    TaskStatus,
)


@pytest.mark.asyncio
async def test_a2a_client_send_and_get_task() -> None:
    """A2AClient send_task and get_task parse standard JSON-RPC 2.0."""
    client = A2AClient()

    now = 1700000000.0
    mock_task = A2ATask(
        task_id="t-mock-1",
        status=TaskStatus.COMPLETED,
        messages=[
            TaskMessage(role=TaskRole.USER, content="Hello", timestamp=now),
            TaskMessage(role=TaskRole.AGENT, content="World", timestamp=now + 1.0),
        ],
        artifacts=[
            TaskArtifact(name="result.txt", uri="data:text/plain,ok"),
        ],
        created_at=now,
        updated_at=now + 1.0,
    )

    with patch.object(client, "_post_json_rpc", new_callable=AsyncMock) as mock_rpc:
        mock_rpc.return_value = JsonRpcResponse(
            result=mock_task.model_dump(by_alias=True),
            id="1",
        )

        sent = await client.send_task(
            "http://peer/rpc", "Hello", bearer_token="token-xyz"
        )
        assert sent.task_id == "t-mock-1"
        assert sent.status == TaskStatus.COMPLETED
        assert mock_rpc.called
        assert mock_rpc.call_args[1]["bearer_token"] == "token-xyz"

        got = await client.get_task("http://peer/rpc", "t-mock-1")
        assert got.task_id == "t-mock-1"
        assert len(got.messages) == 2


@pytest.mark.asyncio
async def test_a2a_client_rpc_error() -> None:
    """A2AClient raises A2ARpcError when JSON-RPC returns error field."""
    client = A2AClient()

    with patch.object(
        client,
        "_post_json_rpc",
        side_effect=A2ARpcError(
            JsonRpcError(code=int(JsonRpcErrorCode.TASK_NOT_FOUND), message="Not found")
        ),
    ):
        with pytest.raises(A2ARpcError) as exc_info:
            await client.get_task("http://peer/rpc", "missing-id")
        assert exc_info.value.error.code == -32004


@pytest.mark.asyncio
async def test_execute_a2a_call_success_and_blocked() -> None:
    """execute_a2a_call handles normal resolution and SSRF blocked policy."""
    now = 1700000000.0
    completed_task = A2ATask(
        task_id="t-success",
        status=TaskStatus.COMPLETED,
        messages=[
            TaskMessage(role=TaskRole.USER, content="Do work", timestamp=now),
            TaskMessage(
                role=TaskRole.AGENT,
                content="Finished work accurately",
                timestamp=now + 2.0,
            ),
        ],
        created_at=now,
        updated_at=now + 2.0,
    )

    mock_client = AsyncMock(spec=A2AClient)
    mock_client.send_task.return_value = completed_task
    mock_client.wait_for_completion.return_value = completed_task

    res = await execute_a2a_call(
        "http://trusted-peer/rpc", "Do work", client=mock_client
    )
    assert res["success"] is True
    assert res["status"] == "completed"
    assert res["answer"] == "Finished work accurately"

    # Test SSRF blocked
    mock_client.send_task.side_effect = A2ASSRFBlockedError(
        "IP 169.254.169.254 blocked"
    )
    blocked_res = await execute_a2a_call(
        "http://169.254.169.254/rpc", "Steal metadata", client=mock_client
    )
    assert blocked_res["success"] is False
    assert blocked_res["status"] == "blocked"
    assert "Security policy blocked" in str(blocked_res["error"])


@pytest.mark.asyncio
async def test_execute_a2a_orchestrate_modes() -> None:
    """execute_a2a_orchestrate handles 'all', 'first', and 'best' strategies."""
    peers = ["http://peer1/rpc", "http://peer2/rpc"]

    # 1. Mode 'all'
    with patch(
        "myrm_agent_harness.toolkits.a2a.tools.execute_a2a_call", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = [
            {"success": True, "answer": "Peer 1 report", "artifacts": []},
            {
                "success": True,
                "answer": "Peer 2 longer report with details",
                "artifacts": [{"name": "a"}],
            },
        ]
        all_res = await execute_a2a_orchestrate(
            peers, "Analyze metrics", mode=FanoutMode.ALL
        )
        assert all_res["success"] is True
        assert all_res["mode"] == "all"
        assert all_res["successful_count"] == 2
        assert len(all_res["results"]) == 2

    # 2. Mode 'first'
    with patch(
        "myrm_agent_harness.toolkits.a2a.tools.execute_a2a_call", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = [
            {"success": True, "answer": "Fastest peer answer", "artifacts": []},
            {"success": True, "answer": "Slow answer", "artifacts": []},
        ]
        first_res = await execute_a2a_orchestrate(
            peers, "Quick ping", mode=FanoutMode.FIRST
        )
        assert first_res["success"] is True
        assert first_res["mode"] == "first"
        assert "Fastest" in str(first_res["result"]["answer"])

    # 3. Mode 'best'
    with patch(
        "myrm_agent_harness.toolkits.a2a.tools.execute_a2a_call", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = [
            {"success": True, "answer": "Short", "artifacts": []},
            {
                "success": True,
                "answer": "Comprehensive synthesized output with full explanation",
                "artifacts": [{"name": "file.json"}],
            },
        ]
        best_res = await execute_a2a_orchestrate(
            peers, "Deep analysis", mode=FanoutMode.BEST
        )
        assert best_res["success"] is True
        assert best_res["mode"] == "best"
        assert "Comprehensive" in str(best_res["best"]["answer"])
