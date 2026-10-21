"""Tests for SubagentExecutor retry mixin workspace isolation paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
    SnapshotStore,
    set_current_message_id,
)
from myrm_agent_harness.agent.meta_tools.file_ops.revert_service import RevertService
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    WorkspacePolicy,
)


@pytest.fixture(autouse=True)
def reset_snapshot_store() -> None:
    SnapshotStore.reset()
    yield
    SnapshotStore.reset()


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
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
            return_value=FakeIsolation(),
        ),
        patch.object(executor, "_run_single_attempt", new_callable=AsyncMock, return_value=_success_result()),
        patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            new_callable=AsyncMock,
        ),
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
async def test_isolated_copy_sync_back_failure_records_merge_warning(
    tmp_path: Path, isolated_config: SubagentConfig
) -> None:
    from myrm_agent_harness.agent.workspace_coordination.merge.merge_warning import (
        format_workspace_merge_failures,
        has_workspace_merge_warning,
        reset_workspace_merge_warning,
    )

    parent_ws = tmp_path / "parent"
    parent_ws.mkdir()
    child_ws = tmp_path / "child"
    sync_back = AsyncMock()

    class FakeIsolation:
        async def __aenter__(self) -> tuple[Path, AsyncMock]:
            return child_ws, sync_back

        async def __aexit__(self, *_args: object) -> None:
            return None

    reset_workspace_merge_warning()
    executor = SubagentExecutor()
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
            return_value=FakeIsolation(),
        ),
        patch.object(executor, "_run_single_attempt", new_callable=AsyncMock, return_value=_success_result()),
        patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            new_callable=AsyncMock,
        ),
        patch(
            "myrm_agent_harness.agent.workspace_coordination.merge.merge_snapshots.apply_isolated_sync_back_with_snapshots",
            new_callable=AsyncMock,
            side_effect=OSError("disk full"),
        ),
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
    assert isinstance(result.result, dict)
    assert result.result.get("workspace_merge_status") == "error"
    assert "disk full" in str(result.result.get("workspace_merge_error"))
    assert has_workspace_merge_warning() is True
    payload = format_workspace_merge_failures()
    assert payload is not None
    assert payload["errors"][0]["message"].startswith("task-1:")
    assert "disk full" in payload["errors"][0]["message"]


@pytest.mark.asyncio
async def test_isolated_copy_sync_back_registers_revert_snapshots(
    tmp_path: Path, isolated_config: SubagentConfig
) -> None:
    """Single ISOLATED_COPY delegate (non-defer) must register Revert snapshots."""
    from myrm_agent_harness.agent.sub_agents.workspace_isolation import isolated_workspace

    parent_ws = tmp_path / "parent"
    parent_ws.mkdir()
    set_current_message_id("msg_single_delegate")

    parent_agent = MagicMock()
    parent_agent._last_context = {
        "chat_id": "chat_single_delegate",
        "workspace_path": str(parent_ws),
    }

    class RealIsolation:
        def __init__(self) -> None:
            self._inner_ctx = isolated_workspace(parent_ws, cleanup_policy={"on_exit": True})

        async def __aenter__(self) -> tuple[Path, AsyncMock]:
            return await self._inner_ctx.__aenter__()

        async def __aexit__(self, *args: object) -> None:
            await self._inner_ctx.__aexit__(*args)

    async def write_in_child(*args: object, **_kwargs: object) -> SubAgentResult:
        context = args[4] if len(args) > 4 and isinstance(args[4], dict) else args[5]
        assert isinstance(context, dict)
        child = Path(str(context.get("workspace_path", "")))
        (child / "analysis.md").write_text("# report\n", encoding="utf-8")
        return _success_result()

    executor = SubagentExecutor()
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
            side_effect=lambda *a, **kw: RealIsolation(),
        ),
        patch.object(executor, "_run_single_attempt", side_effect=write_in_child),
        patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            new_callable=AsyncMock,
        ),
    ):
        result = await executor.run_with_retry(
            task_id="task-1",
            agent_type="worker",
            task_description="run",
            config=isolated_config,
            context={"workspace_path": str(parent_ws)},
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is True
    assert (parent_ws / "analysis.md").is_file()
    changes = await RevertService.get_message_changes("chat_single_delegate", "msg_single_delegate")
    assert len(changes) == 1
    assert changes[0].path == "analysis.md"


@pytest.mark.asyncio
async def test_isolated_copy_defers_sync_when_merge_deferred(tmp_path: Path, isolated_config: SubagentConfig) -> None:
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
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
            return_value=FakeIsolation(),
        ),
        patch.object(
            executor,
            "_run_single_attempt",
            new_callable=AsyncMock,
            return_value=_success_result(result={"text": "payload"}),
        ),
        patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            new_callable=AsyncMock,
        ),
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
async def test_isolated_copy_cleanup_failure_is_swallowed(tmp_path: Path, isolated_config: SubagentConfig) -> None:
    parent_ws = tmp_path / "parent"
    parent_ws.mkdir()
    sync_back = AsyncMock()

    class FailingIsolation:
        async def __aenter__(self) -> tuple[Path, AsyncMock]:
            return tmp_path / "child", sync_back

        async def __aexit__(self, *_args: object) -> None:
            raise RuntimeError("teardown failed")

    executor = SubagentExecutor()
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
            return_value=FailingIsolation(),
        ),
        patch.object(executor, "_run_single_attempt", new_callable=AsyncMock, return_value=_success_result()),
        patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            new_callable=AsyncMock,
        ),
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
