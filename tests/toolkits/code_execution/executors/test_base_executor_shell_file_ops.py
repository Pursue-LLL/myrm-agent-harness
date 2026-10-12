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
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext, ExecutionResult
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
    content = "line with some text 0123456789\n" * 7_500  # ~232 KB, above the 200K-char stdout cap
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


class _FailingAppendExecutor(InProcessExecutor):
    """Fails every append chunk, i.e. any write larger than one chunk fails after its first chunk landed."""

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        if ">>" in context.code:
            return ExecutionResult(success=False, stderr="disk full")
        return await super().execute_bash(context)


class _GarbageReadExecutor(InProcessExecutor):
    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(success=True, stdout="not-hex")


@pytest.mark.asyncio
async def test_failed_atomic_write_keeps_target_and_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    ex = _FailingAppendExecutor()
    ex.bind_workspace(str(tmp_path))
    (tmp_path / "target.bin").write_bytes(b"original")

    with pytest.raises(OSError, match="Cannot write"):
        await ex.write_file_bytes_atomic("target.bin", os.urandom(2 * CHUNK_BYTES))

    assert (tmp_path / "target.bin").read_bytes() == b"original"
    assert [p.name for p in tmp_path.iterdir()] == ["target.bin"]


@pytest.mark.asyncio
async def test_malformed_read_output_raises_oserror(tmp_path: Path) -> None:
    ex = _GarbageReadExecutor()
    ex.bind_workspace(str(tmp_path))

    with pytest.raises(OSError, match="malformed output"):
        await ex.read_file_bytes("anything.bin")


class _RecordingExecutor(InProcessExecutor):
    """Records every shell command; ``overrides`` force the result of commands starting with a given prefix."""

    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []
        self.overrides: dict[str, ExecutionResult] = {}
        self.fail_on_call: int | None = None

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        self.commands.append(context.code)
        if len(self.commands) == self.fail_on_call:
            return ExecutionResult(success=False, stderr="io error")
        for prefix, forced in self.overrides.items():
            if context.code.startswith(prefix):
                return forced
        return await super().execute_bash(context)


@pytest.fixture
def recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _RecordingExecutor:
    monkeypatch.chdir(tmp_path)
    ex = _RecordingExecutor()
    ex.bind_workspace(str(tmp_path))
    return ex


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("size", "write_commands", "read_commands"),
    [(0, 1, 1), (CHUNK_BYTES - 1, 1, 1), (CHUNK_BYTES, 1, 2), (3 * CHUNK_BYTES, 3, 4), (3 * CHUNK_BYTES + 1, 4, 5)],
)
async def test_command_count_is_bounded_by_chunking(
    recorder: _RecordingExecutor, size: int, write_commands: int, read_commands: int
) -> None:
    """Small files cost one command; larger ones cost ceil(size / chunk) plus one size probe on read."""
    payload = os.urandom(size)

    await recorder.write_file_bytes("blob.bin", payload)
    assert len(recorder.commands) == write_commands

    recorder.commands.clear()
    assert await recorder.read_file_bytes("blob.bin") == payload
    assert len(recorder.commands) == read_commands


@pytest.mark.asyncio
async def test_size_probe_failure_is_oserror(recorder: _RecordingExecutor, tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(os.urandom(2 * CHUNK_BYTES))
    recorder.overrides["wc -c"] = ExecutionResult(success=False, stderr="wc broke")

    with pytest.raises(OSError, match="wc broke") as probe_error:
        await recorder.read_file_bytes("blob.bin")
    assert not isinstance(probe_error.value, FileNotFoundError)


@pytest.mark.asyncio
async def test_short_read_is_detected(recorder: _RecordingExecutor, tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(os.urandom(2 * CHUNK_BYTES))
    recorder.overrides["wc -c"] = ExecutionResult(success=True, stdout=str(2 * CHUNK_BYTES + 5))

    with pytest.raises(OSError, match="Short read"):
        await recorder.read_file_bytes("blob.bin")


@pytest.mark.asyncio
async def test_failure_after_first_chunk_is_oserror(recorder: _RecordingExecutor, tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(os.urandom(2 * CHUNK_BYTES))
    recorder.fail_on_call = 3  # first chunk, size probe, then the second chunk fails
    with pytest.raises(OSError, match="io error") as chunk_error:
        await recorder.read_file_bytes("blob.bin")
    assert not isinstance(chunk_error.value, FileNotFoundError)
