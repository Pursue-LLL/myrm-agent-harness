"""Integration: file_write_tool empty content guard on real disk + mutation verifier chain.

Critical path (LocalExecutor, FileOperationService, empty guard, mutation verifier)
is exercised without mocking core file operations or mutation state.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool import (
    create_file_write_tool,
)
from myrm_agent_harness.agent.middlewares._mutation_verifier import (
    format_mutation_failures,
    reset_mutation_state,
)
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    reset_executor,
    set_executor,
)
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import (
    LocalExecutor,
)
from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
    WorkspacePathResolver,
)
from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    bind_workspace_storage_root,
)
from myrm_agent_harness.utils.errors import ToolError

_DUMMY_CONFIG = RunnableConfig()

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _reset_workspace_cache() -> None:
    WorkspacePathResolver._cached_workspace_root = None


def _make_local_executor(workspace: Path) -> LocalExecutor:
    from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import (
        NullProvider,
    )
    from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
        SandboxStatus,
    )

    executor = LocalExecutor(ExecutionConfig())
    executor.bind_workspace(str(workspace))
    null_result = (
        NullProvider(),
        SandboxStatus(enabled=False, provider_name="null", reason="test"),
    )
    patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector.detect_sandbox_provider",
        return_value=null_result,
    ).start()
    patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider",
        return_value=null_result,
    ).start()
    return executor


@pytest.fixture(autouse=True)
def _stop_sandbox_patches() -> None:
    yield
    import unittest.mock

    unittest.mock.patch.stopall()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    _reset_workspace_cache()
    os.environ["WORKSPACE_ROOT"] = str(tmp_path)
    bind_workspace_storage_root(tmp_path)
    yield tmp_path
    os.environ.pop("WORKSPACE_ROOT", None)
    _reset_workspace_cache()


@pytest.mark.asyncio
async def test_empty_content_rejected_no_file_on_disk(workspace: Path) -> None:
    target = workspace / "notes" / "meeting.md"
    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    write_tool = create_file_write_tool()
    try:
        with pytest.raises(ToolError) as exc_info:
            await write_tool.ainvoke(
                {"path": "notes/meeting.md", "content": ""},
                config=_DUMMY_CONFIG,
            )
        assert "empty" in str(exc_info.value.user_hint).lower()
    finally:
        reset_executor(token)

    assert not target.exists()


@pytest.mark.asyncio
async def test_nonempty_content_writes_file_on_disk(workspace: Path) -> None:
    target = workspace / "notes" / "meeting.md"
    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    write_tool = create_file_write_tool()
    try:
        result = await write_tool.ainvoke(
            {"path": "notes/meeting.md", "content": "# Meeting notes\n"},
            config=_DUMMY_CONFIG,
        )
        assert "Successfully created" in str(result)
    finally:
        reset_executor(token)

    assert target.read_text(encoding="utf-8") == "# Meeting notes\n"


@pytest.mark.asyncio
async def test_empty_write_records_mutation_failure_for_sse(workspace: Path) -> None:
    """ToolError → handle_execution_error → mutation verifier → SSE payload."""
    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        handle_execution_error,
    )

    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    write_tool = create_file_write_tool()
    tool_args = {"path": "notes/meeting.md", "content": "   "}

    reset_mutation_state()
    try:
        with pytest.raises(ToolError) as exc_info:
            await write_tool.ainvoke(tool_args, config=_DUMMY_CONFIG)

        with patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            return_value=None,
        ):
            message = await handle_execution_error(
                exc_info.value,
                "file_write_tool",
                "call-empty-write",
                tool_args,
            )

        assert message.status == "error"
        payload = format_mutation_failures()
        assert payload is not None
        assert payload["failed_count"] == 1
        assert payload["files"][0]["path"] == "notes/meeting.md"
        assert payload["files"][0]["tool"] == "file_write_tool"
    finally:
        reset_executor(token)
        reset_mutation_state()

    assert not (workspace / "notes" / "meeting.md").exists()
