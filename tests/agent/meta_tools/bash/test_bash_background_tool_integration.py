"""Real-path integration: bash_tool background spawn + bash_process_* tools.

Exercises C-4/C-5 split modules without mocking BashExecutor or LocalExecutor:
create_bash_tool(run_in_background=True) → spawn_background → registry →
bash_process_list/output/kill.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
    create_bash_process_kill_tool,
    create_bash_process_list_tool,
    create_bash_process_output_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool import create_bash_tool
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import set_executor
from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    bind_workspace_storage_root,
)


def _make_local_executor(workspace: Path) -> object:
    from unittest.mock import patch as mock_patch

    from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
    from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import NullProvider
    from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxStatus

    executor = LocalExecutor(ExecutionConfig())
    executor.bind_workspace(str(workspace))
    null_result = (NullProvider(), SandboxStatus(enabled=False, provider_name="null", reason="test"))
    mock_patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector.detect_sandbox_provider",
        return_value=null_result,
    ).start()
    mock_patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider",
        return_value=null_result,
    ).start()
    return executor


@pytest.fixture(autouse=True)
def _stop_sandbox_patches() -> None:
    yield
    import unittest.mock

    unittest.mock.patch.stopall()


@pytest.fixture(autouse=True)
def _clear_background_registry() -> None:
    registry = get_background_registry()
    registry._entries.clear()  # type: ignore[attr-defined]
    yield
    registry._entries.clear()  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_background_spawn_list_output_kill_full_chain(tmp_path: Path) -> None:
    """Foreground tool spawns bg job; process tools list, poll stdout, then kill."""
    executor = _make_local_executor(tmp_path)
    set_executor(executor)
    bind_workspace_storage_root(tmp_path)

    session_id = "bg-integ-session"
    config: dict[str, object] = {
        "configurable": {
            "context": {
                "session_id": session_id,
                "workspace_path": str(tmp_path),
                "workspaces_storage_root": str(tmp_path),
            }
        }
    }
    marker = "BG_INTEGRATION_MARKER"

    bash_tool = create_bash_tool()
    list_tool = create_bash_process_list_tool()
    output_tool = create_bash_process_output_tool()
    kill_tool = create_bash_process_kill_tool()

    spawn_cmd = (
        f"{sys.executable} -c "
        f"\"import sys,time; print('{marker}', flush=True); time.sleep(120)\""
    )

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
    ):
        spawn_result = await bash_tool.ainvoke(
            {
                "command": spawn_cmd,
                "reason": "integration background spawn",
                "run_in_background": True,
            },
            config=config,
        )

    assert spawn_result["metadata"]["background"] is True
    pid = int(spawn_result["metadata"]["pid"])

    list_result = await list_tool.ainvoke({}, config=config)
    processes = list_result["content"]["processes"]  # type: ignore[index]
    assert any(p["pid"] == pid for p in processes)

    stdout_found = False
    for _ in range(20):
        out = await output_tool.ainvoke({"pid": pid, "max_lines": 20}, config=config)
        content = out["content"]
        if isinstance(content, dict) and marker in str(content.get("stdout", "")):
            stdout_found = True
            break
        await asyncio.sleep(0.05)

    assert stdout_found, "Expected background stdout to contain integration marker"

    kill_result = await kill_tool.ainvoke({"pid": pid, "force": False}, config=config)
    assert kill_result["metadata"]["killed"] is True

    await asyncio.sleep(0.1)
    info = get_background_registry().get(pid)
    assert info is not None
    assert info.status in ("killed", "exited")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_background_spawn_requires_session_id(tmp_path: Path) -> None:
    executor = _make_local_executor(tmp_path)
    set_executor(executor)
    bash_tool = create_bash_tool()

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
        pytest.raises(Exception, match="run_in_background requires"),
    ):
        await bash_tool.ainvoke(
            {
                "command": "sleep 1",
                "reason": "missing session",
                "run_in_background": True,
            },
            config={"configurable": {"context": {}}},
        )
