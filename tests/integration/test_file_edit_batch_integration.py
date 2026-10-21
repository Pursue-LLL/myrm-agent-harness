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
        await read_tool.ainvoke({"paths": [rel_path], "mode": "all"}, config=_DUMMY_CONFIG)

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
        await read_tool.ainvoke({"paths": ["overlap.txt"], "mode": "all"}, config=_DUMMY_CONFIG)

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
        await read_tool.ainvoke({"paths": ["notes.txt"], "mode": "all"}, config=_DUMMY_CONFIG)

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
        await read_tool.ainvoke({"paths": ["partial.txt"], "mode": "all"}, config=_DUMMY_CONFIG)

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
        await read_tool.ainvoke({"paths": ["flat.py"], "mode": "all"}, config=_DUMMY_CONFIG)

        normalized = FileEditInput.model_validate({"path": "flat.py", "old_str": "before", "new_str": "after"})
        edit_tool = create_file_edit_tool()
        result = await edit_tool.ainvoke(normalized.model_dump(), config=_DUMMY_CONFIG)
    finally:
        reset_executor(token)

    assert "Successfully replaced text" in str(result)
    assert target.read_text(encoding="utf-8") == "after\n"


@pytest.mark.asyncio
async def test_cas_version_conflict_self_healing_real_disk_full_flow(workspace: Path) -> None:
    """Full-chain real-disk integration test for CAS version conflict and 1-Turn self-healing.

    1. Writes initial file to disk.
    2. Agent reads file -> Guard establishes baseline hash v1.
    3. External concurrent process modifies file on disk to v2.
    4. Agent attempts edit based on v1 -> ToolError with centered snippet is raised.
    5. Agent rebases edits directly on v2 without calling file_read_tool.
    6. Agent invokes file_edit_tool with rebased edit -> Guard permits edit, disk is updated!
    """
    target = workspace / "service.py"
    initial_func = "def calculate_fee(amount):\n    return amount * 0.10\n"
    initial_content = ("# system header\n" * 250) + initial_func + ("# system footer\n" * 250)
    target.write_text(initial_content, encoding="utf-8")

    executor = _make_local_executor(workspace)
    token = set_executor(executor)
    try:
        # Step 1: Agent reads file
        read_tool = create_file_read_tool()
        await read_tool.ainvoke({"paths": ["service.py"], "mode": "all"}, config=_DUMMY_CONFIG)

        # Step 2: Concurrent process updates file on disk to 0.15
        concurrent_func = "def calculate_fee(amount):\n    return amount * 0.15\n"
        concurrent_content = ("# system header\n" * 250) + concurrent_func + ("# system footer\n" * 250)
        target.write_text(concurrent_content, encoding="utf-8")

        # Step 3: Agent attempts to edit assuming old value 0.10
        edit_tool = create_file_edit_tool()
        with pytest.raises(ToolError) as exc_info:
            await edit_tool.ainvoke(
                {
                    "path": "service.py",
                    "edits": [
                        {
                            "old_str": "def calculate_fee(amount):\n    return amount * 0.10\n",
                            "new_str": "def calculate_fee(amount):\n    return amount * 0.05\n",
                        }
                    ],
                },
                config=_DUMMY_CONFIG,
            )

        err_msg = str(exc_info.value)
        assert "has changed on disk since your last read" in err_msg
        assert "return amount * 0.15" in err_msg
        assert "def calculate_fee(amount):" in err_msg
        assert "Rebase your edits directly on this current content without calling file_read_tool" in err_msg

        # Step 4: Agent performs 1-Turn rebase directly on the received snippet WITHOUT calling file_read_tool
        rebase_result = await edit_tool.ainvoke(
            {
                "path": "service.py",
                "edits": [
                    {
                        "old_str": "def calculate_fee(amount):\n    return amount * 0.15\n",
                        "new_str": "def calculate_fee(amount):\n    return amount * 0.05\n",
                    }
                ],
            },
            config=_DUMMY_CONFIG,
        )

        assert "Successfully replaced text" in str(rebase_result)
        final_disk = target.read_text(encoding="utf-8")
        assert "return amount * 0.05\n" in final_disk
    finally:
        reset_executor(token)

