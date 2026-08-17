"""Integration tests for the three-ceiling file read pack (real chain).

Exercises ``file_read_tool`` end-to-end through a real ``LocalExecutor`` and a
real ``ArtifactVault`` — no mocking of the critical read/truncate path. Covers
the three read outputs (chars / lines / per-line length) across every read mode
(all / preview / stream) and the vault:// continuation hint consistency.

Run under the harness monorepo via ``./myrm test -m integration``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG
from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_truncation import (
    truncate_file_output,
)
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import create_file_read_tool
from myrm_agent_harness.agent.sub_agents.executor_helpers import _auto_vault_or_truncate
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
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


def _bind_executor(ws: str) -> object:
    executor = LocalExecutor(ExecutionConfig(), workspace_path=ws)
    token = set_executor(executor)
    return token, executor


async def _read(tool, paths: list[str], mode: str = "all") -> str:
    result = await tool.ainvoke({"paths": paths, "mode": mode}, config=_CONFIG)
    assert isinstance(result, str)
    return result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_mode_small_file_untouched(workspace: str) -> None:
    path = Path(workspace) / "small.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["small.txt"])
    finally:
        reset_executor(token)
    assert "1|alpha" in result
    assert "2|beta" in result
    assert "3|gamma" in result
    assert "[truncated]" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_mode_long_line_clamped(workspace: str) -> None:
    long = "x" * (DEFAULT_FILE_IO_CONFIG.max_read_line_length + 500)
    path = Path(workspace) / "minified.js"
    path.write_text(f"{long}\nshort\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["minified.js"])
    finally:
        reset_executor(token)
    # Long line must be clamped to the per-line ceiling with the marker.
    assert "... [truncated]" in result
    assert "short" in result
    # A single over-long line must not appear verbatim.
    assert f"|{long}" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preview_mode_applies_per_line_clamp(workspace: str) -> None:
    long = "y" * (DEFAULT_FILE_IO_CONFIG.max_read_line_length + 300)
    path = Path(workspace) / "wide.txt"
    path.write_text(f"{long}\nsecond\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["wide.txt"], mode="preview")
    finally:
        reset_executor(token)
    assert "(preview mode)" in result
    assert "... [truncated]" in result
    assert "second" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_mode_applies_per_line_clamp(workspace: str) -> None:
    long = "z" * (DEFAULT_FILE_IO_CONFIG.max_read_line_length + 400)
    path = Path(workspace) / "stream.dat"
    path.write_text(f"{long}\nlast\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["stream.dat"], mode="stream")
    finally:
        reset_executor(token)
    assert "... [truncated]" in result
    assert "last" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_char_truncation_with_next_offset_continuation(workspace: str) -> None:
    # Enough lines to exceed max_read_chars.
    lines = [f"line-{i:04d}" for i in range(2000)]
    path = Path(workspace) / "big.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        first = await _read(tool, ["big.log"])
    finally:
        reset_executor(token)

    assert "... [truncated]" in first
    m = re.search(r"Use big\.log:(\d+)- to continue", first)
    assert m is not None, f"missing continuation hint in: {first}"
    next_offset = int(m.group(1))

    token2, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        resumed = await _read(tool, [f"big.log:{next_offset}-"])
    finally:
        reset_executor(token2)
    assert f"|{next_offset}|" in resumed or f"{next_offset}|" in resumed


@pytest.mark.integration
@pytest.mark.asyncio
async def test_truncate_output_on_line_boundary_is_complete() -> None:
    # Compiler-grade: never return a half line. Build output > max_chars.
    # Each line has a fixed width so retained lines are trivially complete.
    lines = [f"{i:040d}" for i in range(500)]
    output = "\n".join(lines)
    truncated, was_truncated, meta = truncate_file_output(
        output,
        max_chars=DEFAULT_FILE_IO_CONFIG.max_read_chars,
        path_str="raw.txt",
    )
    assert was_truncated
    assert "next_offset" in meta
    body = truncated.split("\n\n... [truncated]")[0]
    assert body.endswith("\n") is False
    # Every retained line is a complete 40-char line (no half-line fragment).
    assert re.fullmatch(r"(\d{40}\n)*\d{40}", body) is not None
    assert meta["next_offset"] == body.count("\n") + 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vault_read_continuation_hint_uses_line_number(workspace: str) -> None:
    # Build an oversized subagent result that gets auto-vaulted AND exceeds the
    # char read cap so truncation with a line-number continuation hint triggers.
    config = SubagentConfig(system_prompt="t", auto_vault_threshold=80, max_result_tokens=40)
    payload = "CHAIN_" + ("w" * (DEFAULT_FILE_IO_CONFIG.max_read_chars * 2))
    summary = _auto_vault_or_truncate(
        payload,
        config,
        {"workspace_path": workspace},
        "int-read-ceiling",
        "coder",
    )
    vault_match = re.search(r"vault://[a-f0-9-]+", summary)
    assert vault_match is not None

    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, [vault_match.group(0)])
    finally:
        reset_executor(token)

    # Continuation hint for a vault pointer must reference a line number,
    # not a char count (parse_path_with_range only understands line numbers).
    assert "... [truncated]" in result
    assert re.search(r"vault://[a-f0-9-]+:\d+- to continue", result) is not None
    assert re.search(r"vault://[a-f0-9-]+:\d{5,}- to continue", result) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_directory_read_is_dir_real_chain(workspace: str) -> None:
    """Real directory listing through file_read_tool (is_dir branch)."""
    subdir = Path(workspace) / "src"
    subdir.mkdir()
    (subdir / "a.py").write_text("print(1)\n", encoding="utf-8")
    (subdir / "b.py").write_text("print(2)\n", encoding="utf-8")

    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["src"])
    finally:
        reset_executor(token)
    assert "src:" in result
    assert "a.py" in result
    assert "b.py" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_line_range_read_real_chain(workspace: str) -> None:
    """Line-range syntax (file.txt:2-4) through the real service."""
    path = Path(workspace) / "ranged.txt"
    path.write_text("\n".join(f"row-{i}" for i in range(1, 7)) + "\n", encoding="utf-8")

    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["ranged.txt:2-4"])
    finally:
        reset_executor(token)
    assert "2|row-2" in result
    assert "3|row-3" in result
    assert "4|row-4" in result
    assert "(lines 2-4 of 7)" in result
    assert "row-1" not in result
    assert "row-5" not in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_mode_strips_utf8_bom_real_chain(workspace: str) -> None:
    """Reading a UTF-8 BOM file in all mode strips the BOM on display."""
    path = Path(workspace) / "bom.txt"
    path.write_bytes("\ufeffhello\nworld\n".encode("utf-8"))

    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["bom.txt"])
    finally:
        reset_executor(token)
    assert "\ufeff" not in result
    assert "1|hello" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_multiple_files_real_chain(workspace: str) -> None:
    """Reading multiple text paths in one call returns each file's gutter block."""
    (Path(workspace) / "one.txt").write_text("uno\n", encoding="utf-8")
    (Path(workspace) / "two.txt").write_text("dos\n", encoding="utf-8")

    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["one.txt", "two.txt"])
    finally:
        reset_executor(token)
    assert "1|uno" in result
    assert "1|dos" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_directory_truncation_hint_with_many_files(workspace: str) -> None:
    """A directory listing exceeding max_read_chars emits the is_dir truncation hint."""
    big_dir = Path(workspace) / "many"
    big_dir.mkdir()
    for i in range(600):
        (big_dir / f"file_{i:04d}.txt").write_text("x\n", encoding="utf-8")

    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["many"])
    finally:
        reset_executor(token)
    assert "... [truncated]" in result
    assert "Use a more specific path to view fewer items" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preview_mode_large_file_auto_fallback_no_oom(workspace: str) -> None:
    # Wide rows through preview mode: the per-line clamp must prevent a single
    # wide row from dominating the budget.
    lines = ["data-row-" + "a" * 3000 for _ in range(1200)]
    path = Path(workspace) / "bulk.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    token, _executor = _bind_executor(workspace)
    try:
        tool = create_file_read_tool()
        result = await _read(tool, ["bulk.csv"], mode="preview")
    finally:
        reset_executor(token)
    assert "(preview mode)" in result
    assert "... [truncated]" in result
    assert f"|{'a' * 3000}" not in result
