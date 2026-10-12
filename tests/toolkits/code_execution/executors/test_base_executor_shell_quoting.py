"""CodeExecutor shell-based file operation defaults must be byte-exact and treat names as data.

Third-party executors that only implement ``execute`` / ``execute_bash`` inherit these defaults, so a file
name or glob pattern containing a single quote must neither break the command nor run injected commands,
and file content must survive the stdout truncation/scrubbing applied to every shell result.
"""

import gzip
import os
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
from myrm_agent_harness.toolkits.code_execution.executors.shell_file_transfer import CHUNK_BYTES
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


_SECRET_TEXT = "api_key=sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD\npassword=hunter2hunter2\n"


@pytest.mark.asyncio
async def test_text_is_returned_unscrubbed(executor: CodeExecutor, tmp_path: Path) -> None:
    """Shell stdout is scrubbed by ExecutionResult; file content must come back exactly as written."""
    content = f"{_SECRET_TEXT}path={tmp_path}/data/home/user/x\n"
    await executor.write_file("notes.txt", content)

    assert await executor.read_file("notes.txt") == content
    assert (tmp_path / "notes.txt").read_text() == content


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 1, CHUNK_BYTES - 1, CHUNK_BYTES, CHUNK_BYTES + 1, 5 * CHUNK_BYTES + 7])
async def test_bytes_roundtrip_across_chunk_boundaries(executor: CodeExecutor, tmp_path: Path, size: int) -> None:
    payload = os.urandom(size)
    await executor.write_file_bytes("blob.bin", payload)

    assert (tmp_path / "blob.bin").read_bytes() == payload
    assert await executor.read_file_bytes("blob.bin") == payload


@pytest.mark.asyncio
async def test_large_text_over_stdout_cap_is_not_truncated(executor: CodeExecutor) -> None:
    content = "line with some text 0123456789\n" * 20_000  # ~620 KB, above the 200K-char stdout cap
    await executor.write_file("big.txt", content)

    assert await executor.read_file("big.txt") == content


@pytest.mark.asyncio
async def test_write_truncates_and_append_extends_across_chunks(executor: CodeExecutor, tmp_path: Path) -> None:
    await executor.write_file("a.txt", "x" * (3 * CHUNK_BYTES))
    await executor.write_file("a.txt", "short")
    assert (tmp_path / "a.txt").read_text() == "short"

    tail = "y" * (2 * CHUNK_BYTES + 5)
    await executor.append_file("a.txt", tail)
    assert (tmp_path / "a.txt").read_text() == "short" + tail


@pytest.mark.asyncio
async def test_gzip_file_is_decompressed(executor: CodeExecutor) -> None:
    await executor.write_file_bytes("log.txt.gz", gzip.compress(_SECRET_TEXT.encode()))

    assert await executor.read_file("log.txt.gz") == _SECRET_TEXT


@pytest.mark.asyncio
async def test_missing_file_raises_and_failed_write_is_reported(executor: CodeExecutor, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await executor.read_file("absent.txt")
    with pytest.raises(FileNotFoundError):
        await executor.read_file_bytes("absent.bin")

    (tmp_path / "blocker").write_text("not a directory")
    with pytest.raises(OSError, match="Cannot write"):
        await executor.write_file("blocker/child.txt", "data")
