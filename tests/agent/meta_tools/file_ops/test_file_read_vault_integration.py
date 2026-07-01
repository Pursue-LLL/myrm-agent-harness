"""Integration tests for file_read_tool vault reads without mocking vault resolution."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.sub_agents.executor_helpers import _auto_vault_or_truncate
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import create_file_read_tool
from myrm_agent_harness.toolkits.code_execution import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import reset_executor, set_executor
from myrm_agent_harness.toolkits.code_execution.executors.local import LocalExecutor
from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

_DUMMY_CONFIG = RunnableConfig()


def _reset_workspace_cache() -> None:
    WorkspacePathResolver._cached_workspace_root = None


@pytest.fixture
def workspace(tmp_path: Path) -> str:
    ws = str(tmp_path)
    _reset_workspace_cache()
    os.environ["WORKSPACE_ROOT"] = ws
    yield ws
    os.environ.pop("WORKSPACE_ROOT", None)
    _reset_workspace_cache()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_read_tool_reads_auto_vaulted_subagent_result(workspace: str) -> None:
    config = SubagentConfig(system_prompt="t", auto_vault_threshold=80, max_result_tokens=40)
    payload = "CHAIN_" + ("z" * 200)
    summary = _auto_vault_or_truncate(
        payload, config, {"workspace_path": workspace}, "int-read", "coder"
    )
    match = re.search(r"vault://[a-f0-9-]+", summary)
    assert match is not None

    executor = LocalExecutor(ExecutionConfig(), workspace_path=workspace)
    token = set_executor(executor)
    try:
        tool = create_file_read_tool()
        result = await tool.ainvoke({"paths": [match.group(0)], "mode": "all"}, config=_DUMMY_CONFIG)
    finally:
        reset_executor(token)

    assert isinstance(result, str)
    assert payload in result
