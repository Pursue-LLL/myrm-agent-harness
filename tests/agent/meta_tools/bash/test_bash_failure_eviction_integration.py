"""Integration: real bash/python failure keeps stdout visible to the LLM.

Covers the failure-path stdout/stderr symmetry in ``bash_executor_execute_mixin``
end-to-end through ``bash_code_execute_tool``: small stdout is embedded verbatim
in the error message, large stdout is evicted with a truncated banner and stays
readable from sandbox storage. The execution path is real (LocalExecutor), only
non-critical event plumbing is stubbed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import set_executor
from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    bind_workspace_storage_root,
)
from myrm_agent_harness.utils.errors import ToolError

_INTEGRATION_REASON = "integration verification of failure stdout visibility"


def _make_local_executor(workspace: Path) -> object:
    from myrm_agent_harness.toolkits.code_execution.executors.local.executor import (
        LocalExecutor,
    )
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


def _tool_config(workspace: Path, session_id: str) -> dict[str, object]:
    return {
        "configurable": {
            "context": {
                "session_id": session_id,
                "workspace_path": str(workspace),
                "workspaces_storage_root": str(workspace),
            }
        }
    }


@pytest.fixture(autouse=True)
def _stop_sandbox_patches() -> None:
    yield
    import unittest.mock

    unittest.mock.patch.stopall()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bash_failure_small_stdout_visible_in_tool_error(tmp_path: Path) -> None:
    """Small partial stdout stays verbatim in the failure message."""
    set_executor(_make_local_executor(tmp_path))
    bind_workspace_storage_root(tmp_path)
    tool = create_bash_code_execute_tool()

    with (
        patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            AsyncMock(),
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.notify_registry.session_scope",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
        pytest.raises(ToolError) as exc_info,
    ):
        await tool.ainvoke(
            {
                "command": (
                    "python3 -c \"import sys; print('processed row 149'); 1/0\""
                ),
                "reason": _INTEGRATION_REASON,
            },
            config=_tool_config(tmp_path, "small-fail"),
        )

    assert "processed row 149" in str(exc_info.value)
    assert "ZeroDivisionError" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bash_failure_large_stdout_evicted_with_banner(tmp_path: Path) -> None:
    """Large stdout on failure is evicted: banner in message, file on disk."""
    set_executor(_make_local_executor(tmp_path))
    bind_workspace_storage_root(tmp_path)
    tool = create_bash_code_execute_tool()

    with (
        patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            AsyncMock(),
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.notify_registry.session_scope",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
        pytest.raises(ToolError) as exc_info,
    ):
        await tool.ainvoke(
            {
                "command": (
                    "python3 -c \"import sys; "
                    "[print(i) for i in range(2000)]; 1/0\""
                ),
                "reason": _INTEGRATION_REASON,
            },
            config=_tool_config(tmp_path, "large-fail"),
        )

    message = str(exc_info.value)
    assert "ZeroDivisionError" in message
    assert "[LARGE OUTPUT TRUNCATED (2000 lines" in message

    evicted_dir = tmp_path / ".context" / "large-fail" / "evicted"
    assert evicted_dir.is_dir()
    assert any(evicted_dir.iterdir()), "evicted stdout must be readable from disk"
