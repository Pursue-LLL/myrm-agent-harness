"""CodeExecutor shell-based file operation defaults must treat names as data, never as shell syntax.

Third-party executors that only implement ``execute`` / ``execute_bash`` inherit these defaults, so a file
name or glob pattern containing a single quote must neither break the command nor run injected commands.
"""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
from tests.toolkits.code_execution._executor_stub import InProcessExecutor

_QUOTED_NAME = "it's final.txt"
_INJECTION_NAME = "x'; touch PWNED; echo '"
_INJECTION_PATTERN = "*'; touch PWNED_PATTERN; echo '"


@pytest.fixture
def executor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CodeExecutor:
    # The stub runs commands in the process cwd; an injected `touch` would land here and be detectable.
    monkeypatch.chdir(tmp_path)
    ex = InProcessExecutor()
    ex.bind_workspace(str(tmp_path))
    return ex


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [_QUOTED_NAME, _INJECTION_NAME])
async def test_file_ops_roundtrip_with_quote_in_name(executor: CodeExecutor, tmp_path: Path, name: str) -> None:
    await executor.write_file(name, "hello")
    assert await executor.read_file(name) == "hello"

    await executor.append_file(name, " world")
    assert await executor.read_file(name) == "hello world"
    assert await executor.read_file_bytes(name) == b"hello world"

    assert await executor.file_exists(name)
    assert await executor.is_file(name)
    assert not await executor.is_dir(name)

    await executor.delete_file(name)
    assert not await executor.file_exists(name)
    assert not (tmp_path / "PWNED").exists()


@pytest.mark.asyncio
async def test_mkdir_and_is_dir_with_quote_in_name(executor: CodeExecutor, tmp_path: Path) -> None:
    await executor.mkdir(_INJECTION_NAME)

    assert await executor.is_dir(_INJECTION_NAME)
    assert (tmp_path / _INJECTION_NAME).is_dir()
    assert not (tmp_path / "PWNED").exists()


@pytest.mark.asyncio
async def test_list_files_treats_pattern_as_data(executor: CodeExecutor, tmp_path: Path) -> None:
    (tmp_path / _QUOTED_NAME).write_text("a")
    (tmp_path / "plain.txt").write_text("b")

    listed = await executor.list_files(".", "it's*")
    assert [Path(p).name for p in listed] == [_QUOTED_NAME]

    await executor.list_files(".", _INJECTION_PATTERN)
    assert not (tmp_path / "PWNED_PATTERN").exists()
