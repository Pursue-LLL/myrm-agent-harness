"""CodeExecutor base contract: lifecycle defaults, path resolution, atomic replace, middleware, executor registry.

Everything runs against an in-memory scripted executor, so no subprocess is spawned.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.code_execution.executors import base
from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor, CodeExecutorMiddleware
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext, ExecutionResult


class _ScriptedExecutor(CodeExecutor):
    """Answers every bash command from ``respond`` and records the commands."""

    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []
        self.respond: Callable[[str], ExecutionResult] = lambda _command: ExecutionResult(success=True)
        self.closed = 0

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(success=True)

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        self.commands.append(context.code)
        return self.respond(context.code)

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture
def executor(tmp_path: Path) -> _ScriptedExecutor:
    ex = _ScriptedExecutor()
    ex.bind_workspace(str(tmp_path))
    return ex


# --- lifecycle defaults -------------------------------------------------------------------------------------


def test_unbound_workspace_raises() -> None:
    with pytest.raises(RuntimeError, match="Workspace not bound"):
        _ = _ScriptedExecutor().workspace_path


@pytest.mark.asyncio
async def test_async_context_manager_closes_executor(executor: _ScriptedExecutor) -> None:
    async with executor as entered:
        assert entered is executor
    assert executor.closed == 1


@pytest.mark.asyncio
async def test_inherited_defaults(executor: _ScriptedExecutor) -> None:
    assert await CodeExecutor.close(executor) is None
    assert await executor.is_available()
    assert executor.get_executor_name() == "_Scripted"
    assert executor.get_mcp_communication_config() is None
    assert not await executor.save_workspace("s", "/tmp/x")
    assert not await executor.restore_workspace("s", "/tmp/x")
    with pytest.raises(NotImplementedError, match="_ScriptedExecutor"):
        await executor.spawn_background_process(ExecutionContext(code="sleep 1"))


@pytest.mark.asyncio
async def test_default_stream_yields_stdout_then_stderr(executor: _ScriptedExecutor) -> None:
    executor.respond = lambda _command: ExecutionResult(success=True, stdout="out", stderr="err")
    chunks = [chunk async for chunk in executor.execute_bash_stream(ExecutionContext(code="echo"))]
    assert chunks == ["out", "err"]

    executor.respond = lambda _command: ExecutionResult(success=True)
    assert [chunk async for chunk in executor.execute_bash_stream(ExecutionContext(code="echo"))] == []


# --- path resolution ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_path_maps_workspace_prefix_and_absolute_paths(
    executor: _ScriptedExecutor, tmp_path: Path
) -> None:
    root = str(tmp_path.resolve())
    assert await executor.resolve_path("a/b.txt") == f"{root}/a/b.txt"
    assert await executor.resolve_path("/workspace/a.txt") == f"{root}/a.txt"
    assert await executor.resolve_path("/workspace") == root
    assert await executor.resolve_path(f"{root}/inside.txt") == f"{root}/inside.txt"


@pytest.mark.asyncio
@pytest.mark.parametrize("escaping", ["../outside.txt", "/etc/passwd", "a/../../outside.txt"])
async def test_resolve_path_rejects_traversal(executor: _ScriptedExecutor, escaping: str) -> None:
    with pytest.raises(ValueError, match="Path traversal detected"):
        await executor.resolve_path(escaping)


# --- context file access logging ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_file_reads_are_logged(executor: _ScriptedExecutor, caplog: pytest.LogCaptureFixture) -> None:
    executor.respond = lambda _command: ExecutionResult(success=True, stdout="68690a")  # "hi\n" as hex
    with caplog.at_level(logging.INFO):
        assert await executor.read_file(".context/offload.txt") == "hi\n"
    assert any("success=true" in r.getMessage() for r in caplog.records)

    caplog.clear()
    executor.respond = lambda _command: ExecutionResult(success=False, stderr="gone")
    with caplog.at_level(logging.INFO), pytest.raises(FileNotFoundError):
        await executor.read_file(".context/offload.txt")
    assert any(r.levelno == logging.WARNING and "success=false" in r.getMessage() for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO), pytest.raises(FileNotFoundError):
        await executor.read_file("plain.txt")
    assert not any("CONTEXT_ACCESS" in r.getMessage() for r in caplog.records)


# --- atomic replace -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atomic_text_write_goes_through_same_directory_temp_file(
    executor: _ScriptedExecutor, tmp_path: Path
) -> None:
    await executor.write_file_atomic("sub/data.txt", "payload")

    root = str(tmp_path.resolve())
    move = executor.commands[-1]
    assert move.startswith(f"mkdir -p {root}/sub && mv -f {root}/sub/.atomic_")
    assert move.endswith(f"_data.txt {root}/sub/data.txt")


@pytest.mark.asyncio
async def test_atomic_replace_failure_removes_temp_file_and_raises(executor: _ScriptedExecutor) -> None:
    executor.respond = lambda command: (
        ExecutionResult(success=False, stderr="read-only fs") if "mv -f" in command else ExecutionResult(success=True)
    )

    with pytest.raises(OSError, match=re.escape("Atomic replace failed for 'data.bin': read-only fs")):
        await executor.write_file_bytes_atomic("data.bin", b"x")

    assert executor.commands[-1].startswith("rm -f ") and ".atomic_" in executor.commands[-1]


# --- middleware delegation ----------------------------------------------------------------------------------

_DELEGATED_ASYNC: list[tuple[str, tuple[object, ...], object]] = [
    ("execute", (ExecutionContext(code="1"),), ExecutionResult(success=True)),
    ("execute_bash", (ExecutionContext(code="ls"),), ExecutionResult(success=True, stdout="x")),
    ("read_file", ("a.txt",), "text"),
    ("read_file_bytes", ("a.bin",), b"bytes"),
    ("write_file", ("a.txt", "text"), None),
    ("write_file_bytes", ("a.bin", b"bytes"), None),
    ("append_file", ("a.txt", "more"), None),
    ("delete_file", ("a.txt",), None),
    ("file_exists", ("a.txt",), True),
    ("is_file", ("a.txt",), True),
    ("is_dir", ("d",), False),
    ("mkdir", ("d",), None),
    ("list_files", (".", "*.py"), ["a.py"]),
    ("resolve_path", ("a.txt",), "/ws/a.txt"),
    ("is_available", (), True),
    ("save_workspace", ("sid", "/store"), True),
    ("restore_workspace", ("sid", "/store"), True),
    ("close", (), None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "args", "expected"), _DELEGATED_ASYNC, ids=[row[0] for row in _DELEGATED_ASYNC])
async def test_middleware_delegates_async_methods(
    executor: _ScriptedExecutor,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    args: tuple[object, ...],
    expected: object,
) -> None:
    mock = AsyncMock(return_value=expected)
    monkeypatch.setattr(executor, name, mock)

    assert await getattr(CodeExecutorMiddleware(executor), name)(*args) == expected
    mock.assert_awaited_once_with(*args)


@pytest.mark.asyncio
async def test_middleware_delegates_stream_name_config_and_workspace(
    executor: _ScriptedExecutor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def stream(_context: ExecutionContext) -> AsyncIterator[str]:
        yield "chunk"

    monkeypatch.setattr(executor, "execute_bash_stream", stream)
    monkeypatch.setattr(executor, "get_executor_name", MagicMock(return_value="Inner"))
    config = MagicMock()
    monkeypatch.setattr(executor, "get_mcp_communication_config", MagicMock(return_value=config))
    middleware = CodeExecutorMiddleware(executor)

    assert [c async for c in middleware.execute_bash_stream(ExecutionContext(code="x"))] == ["chunk"]
    assert middleware.get_executor_name() == "Inner"
    assert middleware.get_mcp_communication_config() is config
    assert middleware.workspace_path == str(tmp_path)

    middleware.bind_workspace("/other")
    assert executor.workspace_path == "/other"

    replacement = type(executor.metrics)()
    middleware.metrics = replacement
    assert executor.metrics is replacement
    assert middleware.metrics is replacement


# --- executor registry --------------------------------------------------------------------------------------


def test_contextvar_binding_round_trip(executor: _ScriptedExecutor) -> None:
    assert base.get_executor() is None
    with pytest.raises(RuntimeError, match="CodeExecutor not available"):
        base.require_executor()

    token = base.set_executor(executor)
    try:
        assert base.get_executor() is executor
        assert base.require_executor() is executor
    finally:
        base.reset_executor(token)
    assert base.get_executor() is None


@pytest.fixture
def clean_stash() -> None:
    base.clear_all_stashed_executors_for_tests()


@pytest.mark.usefixtures("clean_stash")
def test_stash_lookup_and_sync_clear_without_running_loop(executor: _ScriptedExecutor) -> None:
    base.stash_executor_for_session("sid-1", executor)
    assert base.get_stashed_executor("sid-1") is executor

    base.clear_stashed_executor("sid-1")  # no running loop: entry dropped, close is not scheduled
    assert base.get_stashed_executor("sid-1") is None
    assert executor.closed == 0

    base.clear_stashed_executor("never-stashed")


@pytest.mark.asyncio
@pytest.mark.usefixtures("clean_stash")
async def test_clear_stashed_executor_closes_in_background_when_loop_runs(executor: _ScriptedExecutor) -> None:
    base.stash_executor_for_session("sid-2", executor)
    base.clear_stashed_executor("sid-2")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert executor.closed == 1
    assert base.get_stashed_executor("sid-2") is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("clean_stash")
async def test_clear_and_close_stashed_executor_survives_close_failure(
    executor: _ScriptedExecutor, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    base.stash_executor_for_session("sid-3", executor)
    await base.clear_and_close_stashed_executor("sid-3")
    assert executor.closed == 1

    failing = _ScriptedExecutor()
    monkeypatch.setattr(failing, "close", AsyncMock(side_effect=RuntimeError("boom")))
    base.stash_executor_for_session("sid-4", failing)
    with caplog.at_level(logging.WARNING):
        await base.clear_and_close_stashed_executor("sid-4")
    assert any("Failed to close stashed executor for session sid-4" in r.getMessage() for r in caplog.records)

    await base.clear_and_close_stashed_executor("never-stashed")
