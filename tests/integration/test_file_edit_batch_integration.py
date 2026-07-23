"""Integration: file_edit_tool batch atomic edits on real disk via LocalExecutor.

Critical path (LocalExecutor, ExecutorStorageAdapter, FileOperationService,
batch_str_replace, integrity guard) is exercised without mocks.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool import (
    create_file_edit_tool,
)
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import (
    create_file_read_tool,
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
    from unittest.mock import patch

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


async def _read_then_edit(
    workspace: Path,
    *,
    rel_path: str,
    edits: list[dict[str, str]],
    verify_command: str | None = None,
) -> str:
    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    try:
        read_tool = create_file_read_tool()
        await read_tool.ainvoke(
            {"paths": [rel_path], "mode": "all"}, config=_DUMMY_CONFIG
        )

        edit_tool = create_file_edit_tool()
        payload: dict[str, object] = {"path": rel_path, "edits": edits}
        if verify_command is not None:
            payload["verify_command"] = verify_command
        return await edit_tool.ainvoke(payload, config=_DUMMY_CONFIG)
    finally:
        reset_executor(token)


@pytest.mark.asyncio
async def test_batch_edits_atomic_write_on_disk(workspace: Path) -> None:
    target = workspace / "sample.py"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = await _read_then_edit(
        workspace,
        rel_path="sample.py",
        edits=[
            {"old_str": "alpha", "new_str": "ALPHA"},
            {"old_str": "gamma", "new_str": "GAMMA"},
        ],
    )

    assert "Successfully replaced text" in str(result)
    assert target.read_text(encoding="utf-8") == "ALPHA\nbeta\nGAMMA\n"


@pytest.mark.asyncio
async def test_batch_edits_overlap_rejected_no_disk_change(workspace: Path) -> None:
    original = "abcdef\n"
    target = workspace / "overlap.txt"
    target.write_text(original, encoding="utf-8")

    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    try:
        read_tool = create_file_read_tool()
        await read_tool.ainvoke(
            {"paths": ["overlap.txt"], "mode": "all"}, config=_DUMMY_CONFIG
        )

        edit_tool = create_file_edit_tool()
        with pytest.raises(ToolError, match="overlap"):
            await edit_tool.ainvoke(
                {
                    "path": "overlap.txt",
                    "edits": [
                        {"old_str": "abc", "new_str": "1"},
                        {"old_str": "bcd", "new_str": "2"},
                    ],
                },
                config=_DUMMY_CONFIG,
            )
    finally:
        reset_executor(token)

    assert target.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_batch_edits_verify_failure_rolls_back(workspace: Path) -> None:
    target = workspace / "notes.txt"
    original = "version=1\n"
    target.write_text(original, encoding="utf-8")

    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    try:
        read_tool = create_file_read_tool()
        await read_tool.ainvoke(
            {"paths": ["notes.txt"], "mode": "all"}, config=_DUMMY_CONFIG
        )

        edit_tool = create_file_edit_tool()
        with pytest.raises(ToolError, match="verification failed"):
            await edit_tool.ainvoke(
                {
                    "path": "notes.txt",
                    "edits": [{"old_str": "version=1", "new_str": "version=2"}],
                    "verify_command": "false",
                },
                config=_DUMMY_CONFIG,
            )
    finally:
        reset_executor(token)

    assert target.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_read_before_edit_guard_blocks_without_read(workspace: Path) -> None:
    target = workspace / "guard.txt"
    target.write_text("secret\n", encoding="utf-8")

    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    try:
        edit_tool = create_file_edit_tool()
        with pytest.raises(ToolError, match="has not been read"):
            await edit_tool.ainvoke(
                {
                    "path": "guard.txt",
                    "edits": [{"old_str": "secret", "new_str": "public"}],
                },
                config=_DUMMY_CONFIG,
            )
    finally:
        reset_executor(token)

    assert target.read_text(encoding="utf-8") == "secret\n"


@pytest.mark.asyncio
async def test_second_edit_not_found_leaves_disk_unchanged(workspace: Path) -> None:
    target = workspace / "partial.txt"
    original = "keep\n"
    target.write_text(original, encoding="utf-8")

    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    try:
        read_tool = create_file_read_tool()
        await read_tool.ainvoke(
            {"paths": ["partial.txt"], "mode": "all"}, config=_DUMMY_CONFIG
        )

        edit_tool = create_file_edit_tool()
        with pytest.raises(ToolError, match="not found"):
            await edit_tool.ainvoke(
                {
                    "path": "partial.txt",
                    "edits": [
                        {"old_str": "keep", "new_str": "changed"},
                        {"old_str": "missing", "new_str": "x"},
                    ],
                },
                config=_DUMMY_CONFIG,
            )
    finally:
        reset_executor(token)

    assert target.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_delete_via_empty_new_str_on_disk(workspace: Path) -> None:
    target = workspace / "trim.txt"
    target.write_text("alpha\nremove_me\nomega\n", encoding="utf-8")

    result = await _read_then_edit(
        workspace,
        rel_path="trim.txt",
        edits=[{"old_str": "remove_me\n", "new_str": ""}],
    )

    assert "Successfully replaced text" in str(result)
    assert target.read_text(encoding="utf-8") == "alpha\nomega\n"


@pytest.mark.asyncio
async def test_normalizer_flat_old_str_payload_on_disk(workspace: Path) -> None:
    from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool import (
        FileEditInput,
    )

    target = workspace / "flat.py"
    target.write_text("before\n", encoding="utf-8")

    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    try:
        read_tool = create_file_read_tool()
        await read_tool.ainvoke(
            {"paths": ["flat.py"], "mode": "all"}, config=_DUMMY_CONFIG
        )

        normalized = FileEditInput.model_validate(
            {"path": "flat.py", "old_str": "before", "new_str": "after"}
        )
        edit_tool = create_file_edit_tool()
        result = await edit_tool.ainvoke(normalized.model_dump(), config=_DUMMY_CONFIG)
    finally:
        reset_executor(token)

    assert "Successfully replaced text" in str(result)
    assert target.read_text(encoding="utf-8") == "after\n"
