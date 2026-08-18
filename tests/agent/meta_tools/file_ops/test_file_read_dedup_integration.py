"""Integration tests for read-time dedup (real chain).

Exercises ``file_read_tool`` end-to-end through a real ``LocalExecutor`` — no
mocking of the critical read/dedup path. Verifies the dedup lifecycle against
real file mtime:

- first read returns full content (MISS)
- unchanged re-read returns a lightweight stub (STUB)
- repeated unchanged re-reads hard-block (BLOCKED)
- a write invalidates dedup so the next read is fresh (MISS)
- an mtime change (external edit) also forces a fresh read (MISS)

Run under the harness monorepo via ``./myrm test -m integration``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.core.read_dedup import reset_all_read_dedup
from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool import create_file_edit_tool
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import create_file_read_tool
from myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool import create_file_write_tool
from myrm_agent_harness.toolkits.code_execution import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import reset_executor, set_executor
from myrm_agent_harness.toolkits.code_execution.executors.local import LocalExecutor
from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

_CONFIG = RunnableConfig()


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


def _bind_executor(ws: str) -> tuple[object, LocalExecutor]:
    executor = LocalExecutor(ExecutionConfig(), workspace_path=ws)
    token = set_executor(executor)
    return token, executor


async def _read(tool, paths: list[str]) -> str:
    result = await tool.ainvoke({"paths": paths, "mode": "all"}, config=_CONFIG)
    assert isinstance(result, str)
    return result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_first_read_returns_full_content(workspace: str) -> None:
    """First read of an unchanged file returns the full gutter content (MISS)."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["dedup.txt"])
    finally:
        reset_executor(token)
    assert "1|alpha" in result
    assert "2|beta" in result
    assert "File unchanged" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unchanged_reread_returns_stub(workspace: str) -> None:
    """Re-reading an unchanged file in the same executor returns a stub."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        first = await _read(tool, ["dedup.txt"])
        second = await _read(tool, ["dedup.txt"])
    finally:
        reset_executor(token)
    assert "1|alpha" in first
    assert "File unchanged since last read: dedup.txt" in second
    assert "1|alpha" not in second


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repeated_unchanged_reread_hard_blocks(workspace: str) -> None:
    """Repeated unchanged reads escalate from stub to a hard block."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        await _read(tool, ["dedup.txt"])  # MISS
        second = await _read(tool, ["dedup.txt"])  # STUB
        third = await _read(tool, ["dedup.txt"])  # BLOCKED
    finally:
        reset_executor(token)
    assert "File unchanged since last read" in second
    assert "BLOCKED: file unchanged after 2 consecutive reads: dedup.txt" in third


@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_invalidates_dedup(workspace: str) -> None:
    """After a write, the next read is fresh (dedup invalidated)."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        await _read(tool, ["dedup.txt"])  # MISS, records state
        # Simulate a write by modifying the file on disk (mtime changes).
        path.write_text("alpha\nbeta\n", encoding="utf-8")
        result = await _read(tool, ["dedup.txt"])
    finally:
        reset_executor(token)
    assert "1|alpha" in result
    assert "2|beta" in result
    assert "File unchanged" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mtime_change_forces_fresh_read(workspace: str) -> None:
    """An external mtime change (no write through the tool) forces a fresh read."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        await _read(tool, ["dedup.txt"])  # MISS, records mtime
        # External edit: change content AND bump mtime.
        path.write_text("gamma\n", encoding="utf-8")
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 2))
        result = await _read(tool, ["dedup.txt"])
    finally:
        reset_executor(token)
    assert "1|gamma" in result
    assert "File unchanged" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dedup_state_isolated_per_executor(workspace: str) -> None:
    """Dedup state is per-executor: a fresh executor re-reads the file fully."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\n", encoding="utf-8")

    token1, _executor1 = _bind_executor(workspace)
    try:
        tool1 = create_file_read_tool()
        await _read(tool1, ["dedup.txt"])  # MISS in executor 1
        second = await _read(tool1, ["dedup.txt"])  # STUB in executor 1
    finally:
        reset_executor(token1)
    assert "File unchanged" in second

    # A brand-new executor has no dedup state for this file.
    token2, _executor2 = _bind_executor(workspace)
    try:
        tool2 = create_file_read_tool()
        result = await _read(tool2, ["dedup.txt"])
    finally:
        reset_executor(token2)
    assert "1|alpha" in result
    assert "File unchanged" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_write_tool_creates_then_edit_invalidates_dedup(workspace: str) -> None:
    """A real file_write_tool creates a file; a later edit invalidates dedup."""
    token, _executor = _bind_executor(workspace)
    try:
        read_tool = create_file_read_tool()
        write_tool = create_file_write_tool()
        edit_tool = create_file_edit_tool()
        # write_tool is create-only: the file must not exist yet.
        write_result = await write_tool.ainvoke(
            {"path": "dedup.txt", "content": "alpha\n"}, config=_CONFIG
        )
        assert isinstance(write_result, str)
        await _read(read_tool, ["dedup.txt"])  # MISS, records state
        second = await _read(read_tool, ["dedup.txt"])  # STUB
        assert "File unchanged" in second
        # Real edit through the tool invalidates dedup.
        edit_result = await edit_tool.ainvoke(
            {"path": "dedup.txt", "edits": [{"old_str": "alpha", "new_str": "alpha\nbeta"}]},
            config=_CONFIG,
        )
        assert isinstance(edit_result, str)
        result = await _read(read_tool, ["dedup.txt"])
    finally:
        reset_executor(token)
    assert "1|alpha" in result
    assert "2|beta" in result
    assert "File unchanged" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_edit_tool_invalidates_dedup(workspace: str) -> None:
    """A real file_edit_tool (str_replace) call invalidates dedup."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        read_tool = create_file_read_tool()
        edit_tool = create_file_edit_tool()
        await _read(read_tool, ["dedup.txt"])  # MISS, records state
        edit_result = await edit_tool.ainvoke(
            {"path": "dedup.txt", "edits": [{"old_str": "beta", "new_str": "gamma"}]},
            config=_CONFIG,
        )
        assert isinstance(edit_result, str)
        result = await _read(read_tool, ["dedup.txt"])
    finally:
        reset_executor(token)
    assert "1|alpha" in result
    assert "2|gamma" in result
    assert "File unchanged" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_view_range_is_distinct_dedup_key(workspace: str) -> None:
    """A full read and a range read use distinct dedup keys (both return content)."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("\n".join(f"row-{i}" for i in range(1, 7)) + "\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        full = await _read(tool, ["dedup.txt"])  # MISS (key: "")
        ranged = await _read(tool, ["dedup.txt:2-4"])  # MISS (key: "2:4")
    finally:
        reset_executor(token)
    assert "1|row-1" in full
    assert "2|row-2" in ranged
    assert "3|row-3" in ranged
    assert "4|row-4" in ranged
    assert "File unchanged" not in ranged


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reset_all_read_dedup_forces_fresh_read(workspace: str) -> None:
    """After reset_all_read_dedup, a previously-stubbed file is read fresh."""
    path = Path(workspace) / "dedup.txt"
    path.write_text("alpha\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        await _read(tool, ["dedup.txt"])  # MISS
        second = await _read(tool, ["dedup.txt"])  # STUB
        assert "File unchanged" in second
        # Simulate the post-compression reset hook.
        reset_all_read_dedup()
        result = await _read(tool, ["dedup.txt"])
    finally:
        reset_executor(token)
    assert "1|alpha" in result
    assert "File unchanged" not in result
