"""Tests for SubagentExecutor retry mixin workspace isolation paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    WorkspacePolicy,
)


@pytest.fixture
def isolated_config() -> SubagentConfig:
    return SubagentConfig(
        system_prompt="system",
        budget_tokens=10000,
        max_result_tokens=5000,
        timeout_seconds=60,
        max_retries=1,
        retry_backoff_seconds=0,
        workspace_policy=WorkspacePolicy.ISOLATED_COPY,
    )


def _success_result(*, result: object = "done") -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id="task-1",
        agent_type="worker",
        result=result,
        completed_at=0.0,
        status=SubAgentStatus.COMPLETED,
    )


@pytest.mark.asyncio
async def test_isolated_copy_runs_sync_back_on_success(tmp_path: Path, isolated_config: SubagentConfig) -> None:
    parent_ws = tmp_path / "parent"
    parent_ws.mkdir()
    sync_back = AsyncMock()
    child_ws = tmp_path / "child"

    class FakeIsolation:
        async def __aenter__(self) -> tuple[Path, AsyncMock]:
            return child_ws, sync_back

        async def __aexit__(self, *_args: object) -> None:
            return None

    executor = SubagentExecutor()
    with patch(
        "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
        return_value=FakeIsolation(),
    ), patch.object(
        executor, "_run_single_attempt", new_callable=AsyncMock, return_value=_success_result()
    ), patch(
        "myrm_agent_harness.agent.hooks.executor.fire_hook",
        new_callable=AsyncMock,
    ):
        context: dict[str, object] = {"workspace_path": str(parent_ws)}
        result = await executor.run_with_retry(
            task_id="task-1",
            agent_type="worker",
            task_description="run",
            config=isolated_config,
            context=context,
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_agent=MagicMock(),
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is True
    sync_back.assert_awaited_once()


@pytest.mark.asyncio
async def test_isolated_copy_defers_sync_when_merge_deferred(
    tmp_path: Path, isolated_config: SubagentConfig
) -> None:
    parent_ws = tmp_path / "parent"
    parent_ws.mkdir()
    sync_back = AsyncMock()
    child_ws = tmp_path / "child"

    class FakeIsolation:
        async def __aenter__(self) -> tuple[Path, AsyncMock]:
            return child_ws, sync_back

        async def __aexit__(self, *_args: object) -> None:
            return None

    executor = SubagentExecutor()
    with patch(
        "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
        return_value=FakeIsolation(),
    ), patch.object(
        executor,
        "_run_single_attempt",
        new_callable=AsyncMock,
        return_value=_success_result(result={"text": "payload"}),
    ), patch(
        "myrm_agent_harness.agent.hooks.executor.fire_hook",
        new_callable=AsyncMock,
    ):
        context: dict[str, object] = {
            "workspace_path": str(parent_ws),
            "_defer_workspace_merge": True,
        }
        result = await executor.run_with_retry(
            task_id="task-1",
            agent_type="worker",
            task_description="run",
            config=isolated_config,
            context=context,
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_agent=MagicMock(),
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is True
    sync_back.assert_not_called()
    assert isinstance(result.result, dict)
    assert result.result["_workspace_sync_back"] is sync_back
    assert result.result["_isolated_parent_workspace"] == str(parent_ws)


@pytest.mark.asyncio
async def test_isolated_copy_cleanup_failure_is_swallowed(
    tmp_path: Path, isolated_config: SubagentConfig
) -> None:
    parent_ws = tmp_path / "parent"
    parent_ws.mkdir()
    sync_back = AsyncMock()

    class FailingIsolation:
        async def __aenter__(self) -> tuple[Path, AsyncMock]:
            return tmp_path / "child", sync_back

        async def __aexit__(self, *_args: object) -> None:
            raise RuntimeError("teardown failed")

    executor = SubagentExecutor()
    with patch(
        "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
        return_value=FailingIsolation(),
    ), patch.object(
        executor, "_run_single_attempt", new_callable=AsyncMock, return_value=_success_result()
    ), patch(
        "myrm_agent_harness.agent.hooks.executor.fire_hook",
        new_callable=AsyncMock,
    ):
        result = await executor.run_with_retry(
            task_id="task-1",
            agent_type="worker",
            task_description="run",
            config=isolated_config,
            context={"workspace_path": str(parent_ws)},
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_agent=MagicMock(),
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is True
