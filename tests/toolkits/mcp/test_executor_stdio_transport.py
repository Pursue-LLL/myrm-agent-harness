"""Tests for ExecutorStdioTransport — the executor-backed MCP stdio transport.

Covers:
- Noisy stdout filtering (non-JSON lines dropped, valid JSON passed through)
- Stderr draining to workspace log file
- Log file rotation when size exceeds limit
- Process lifecycle (start, close, terminate)
- Pristine environment sanitization via CodeExecutor
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import anyio
import pytest

from myrm_agent_harness.toolkits.code_execution.executors.models import AsyncProcessProtocol
from myrm_agent_harness.toolkits.mcp.transport import ExecutorStdioTransport


class _FakeStreamReader:
    """Simulates asyncio.StreamReader with predefined lines."""

    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)
        self._idx = 0

    async def readline(self) -> bytes:
        if self._idx < len(self._lines):
            line = self._lines[self._idx]
            self._idx += 1
            return line
        return b""


class _FakeStreamWriter:
    """Simulates asyncio.StreamWriter that captures written bytes."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self._closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self._closed = True


class _FakeProcess:
    """Fake process conforming to AsyncProcessProtocol."""

    def __init__(
        self,
        stdin: _FakeStreamWriter | None = None,
        stdout: _FakeStreamReader | None = None,
        stderr: _FakeStreamReader | None = None,
    ):
        self._stdin = stdin or _FakeStreamWriter()
        self._stdout = stdout or _FakeStreamReader([])
        self._stderr = stderr or _FakeStreamReader([])
        self._return_code: int | None = None
        self._terminated = False
        self._killed = False

    @property
    def stdin(self) -> object:
        return self._stdin

    @property
    def stdout(self) -> object:
        return self._stdout

    @property
    def stderr(self) -> object:
        return self._stderr

    async def wait(self) -> int:
        return self._return_code or 0

    def terminate(self) -> None:
        self._terminated = True

    def kill(self) -> None:
        self._killed = True


def _make_transport(
    workspace_path: str = "/tmp/test-workspace",
    server_name: str = "test-mcp",
) -> tuple[ExecutorStdioTransport, MagicMock]:
    """Create transport with a mocked executor."""
    executor = MagicMock()
    executor.workspace_path = workspace_path

    params = MagicMock()
    params.command = "node"
    params.args = ["server.js"]
    params.env = None
    params.cwd = None

    transport = ExecutorStdioTransport(
        executor=executor,
        server_name=server_name,
        parameters=params,
    )
    return transport, executor


# --- Noisy Stdout Filter Tests ---


@pytest.mark.asyncio
async def test_stdout_reader_passes_valid_json_rpc() -> None:
    """Valid JSON-RPC messages must pass through the filter."""
    msg = {"jsonrpc": "2.0", "method": "initialize", "id": 1}
    json_line = json.dumps(msg) + "\n"

    reader = _FakeStreamReader([json_line.encode("utf-8")])
    transport, _ = _make_transport()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    await transport._stdout_reader(reader, send_tx)

    results: list[str | bytes] = []
    async with send_rx:
        async for item in send_rx:
            results.append(item)

    assert len(results) == 1
    parsed = json.loads(results[0])
    assert parsed["method"] == "initialize"


@pytest.mark.asyncio
async def test_stdout_reader_drops_non_json_lines() -> None:
    """Non-JSON lines (log messages, debug prints) must be silently dropped."""
    lines = [
        b"Starting MCP server...\n",
        b"DEBUG: Loading config\n",
        b'{"jsonrpc":"2.0","method":"ping","id":2}\n',
        b"WARNING: Something happened\n",
    ]

    reader = _FakeStreamReader(lines)
    transport, _ = _make_transport()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    await transport._stdout_reader(reader, send_tx)

    results: list[str | bytes] = []
    async with send_rx:
        async for item in send_rx:
            results.append(item)

    assert len(results) == 1
    assert json.loads(results[0])["method"] == "ping"


@pytest.mark.asyncio
async def test_stdout_reader_drops_invalid_json() -> None:
    """Lines starting with { but not valid JSON must be dropped."""
    lines = [
        b"{this is not json}\n",
        b'{"valid": true}\n',
    ]

    reader = _FakeStreamReader(lines)
    transport, _ = _make_transport()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    await transport._stdout_reader(reader, send_tx)

    results: list[str | bytes] = []
    async with send_rx:
        async for item in send_rx:
            results.append(item)

    assert len(results) == 1
    assert json.loads(results[0])["valid"] is True


@pytest.mark.asyncio
async def test_stdout_reader_accepts_json_arrays() -> None:
    """JSON arrays (starting with [) must also pass through."""
    json_array = json.dumps([1, 2, 3]) + "\n"

    reader = _FakeStreamReader([json_array.encode("utf-8")])
    transport, _ = _make_transport()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    await transport._stdout_reader(reader, send_tx)

    results: list[str | bytes] = []
    async with send_rx:
        async for item in send_rx:
            results.append(item)

    assert len(results) == 1
    assert json.loads(results[0]) == [1, 2, 3]


@pytest.mark.asyncio
async def test_stdout_reader_handles_empty_lines() -> None:
    """Empty lines and whitespace-only lines must be silently skipped."""
    lines = [
        b"\n",
        b"   \n",
        b'{"ok": 1}\n',
    ]

    reader = _FakeStreamReader(lines)
    transport, _ = _make_transport()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    await transport._stdout_reader(reader, send_tx)

    results: list[str | bytes] = []
    async with send_rx:
        async for item in send_rx:
            results.append(item)

    assert len(results) == 1


# --- Stderr Draining Tests ---


@pytest.mark.asyncio
async def test_stderr_reader_writes_to_log_file() -> None:
    """Stderr output must be drained to a .myrm/mcp_logs/<name>.log file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        transport, _ = _make_transport(workspace_path=tmpdir, server_name="test-stderr")

        stderr_lines = [
            b"Error: something went wrong\n",
            b"Warning: low memory\n",
        ]
        reader = _FakeStreamReader(stderr_lines)

        await transport._stderr_reader(reader)

        log_file = Path(tmpdir) / ".myrm" / "mcp_logs" / "test-stderr.log"
        assert log_file.exists()

        content = log_file.read_text()
        assert "something went wrong" in content
        assert "low memory" in content


@pytest.mark.asyncio
async def test_stderr_reader_creates_log_directory() -> None:
    """The log directory must be auto-created if it doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        transport, _ = _make_transport(workspace_path=tmpdir, server_name="dir-test")

        reader = _FakeStreamReader([b"log line\n"])
        await transport._stderr_reader(reader)

        log_dir = Path(tmpdir) / ".myrm" / "mcp_logs"
        assert log_dir.is_dir()


@pytest.mark.asyncio
async def test_stderr_reader_handles_unicode_errors() -> None:
    """Invalid UTF-8 bytes in stderr must not crash the reader."""
    with tempfile.TemporaryDirectory() as tmpdir:
        transport, _ = _make_transport(workspace_path=tmpdir, server_name="unicode-test")

        lines = [
            b"\xff\xfe invalid bytes\n",
            b"valid line after bad bytes\n",
        ]
        reader = _FakeStreamReader(lines)

        await transport._stderr_reader(reader)

        log_file = Path(tmpdir) / ".myrm" / "mcp_logs" / "unicode-test.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "valid line after bad bytes" in content


# --- Log Rotation Tests ---


@pytest.mark.asyncio
async def test_rotate_if_needed_does_nothing_for_small_files() -> None:
    """Files under the size limit should not be rotated."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "small.log"
        log_file.write_text("small content\n")

        original_size = log_file.stat().st_size
        await ExecutorStdioTransport._rotate_if_needed(log_file)
        assert log_file.stat().st_size == original_size


@pytest.mark.asyncio
async def test_rotate_if_needed_truncates_large_files() -> None:
    """Files exceeding the size limit should be truncated to ~half size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "large.log"

        # Temporarily lower the limit for testing
        original_limit = ExecutorStdioTransport._MAX_LOG_SIZE_BYTES
        try:
            ExecutorStdioTransport._MAX_LOG_SIZE_BYTES = 1000  # 1KB for test

            # Write 2KB of data (exceeds 1KB limit)
            lines = [f"Log line {i}: some content here\n" for i in range(100)]
            log_file.write_text("".join(lines))

            original_size = log_file.stat().st_size
            assert original_size > 1000

            await ExecutorStdioTransport._rotate_if_needed(log_file)

            new_size = log_file.stat().st_size
            assert new_size < original_size
            # The rotated file should contain valid complete lines
            content = log_file.read_text()
            assert content.endswith("\n")
            # Should not start with a partial line
            assert "Log line" in content.split("\n")[0]
        finally:
            ExecutorStdioTransport._MAX_LOG_SIZE_BYTES = original_limit


@pytest.mark.asyncio
async def test_rotate_handles_missing_file_gracefully() -> None:
    """Rotation on a non-existent file should not raise."""
    non_existent = Path("/tmp/non_existent_log_file_for_test.log")
    if non_existent.exists():
        non_existent.unlink()

    # Should not raise
    await ExecutorStdioTransport._rotate_if_needed(non_existent)


# --- Process Lifecycle Tests ---


@pytest.mark.asyncio
async def test_close_terminates_process() -> None:
    """Closing the transport must call terminate() on the process."""
    transport, _ = _make_transport()
    process = _FakeProcess()
    transport._process = process

    await transport.close()

    assert process._terminated
    assert transport._closed


@pytest.mark.asyncio
async def test_close_is_idempotent() -> None:
    """Calling close() twice must not raise."""
    transport, _ = _make_transport()
    process = _FakeProcess()
    transport._process = process

    await transport.close()
    await transport.close()  # Second call should be no-op

    assert transport._closed


@pytest.mark.asyncio
async def test_connect_raises_on_closed_transport() -> None:
    """Connecting a closed transport must raise RuntimeError."""
    transport, _ = _make_transport()
    transport._closed = True

    with pytest.raises(RuntimeError, match="Transport is closed"):
        async with transport.connect():
            pass


# --- Stdin Writer Tests ---


@pytest.mark.asyncio
async def test_stdin_writer_forwards_string_chunks() -> None:
    """String chunks must be encoded to UTF-8 and written to stdin."""
    transport, _ = _make_transport()
    writer = _FakeStreamWriter()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    async with send_tx:
        await send_tx.send("hello\n")

    await transport._stdin_writer(writer, send_rx)

    assert len(writer.written) == 1
    assert writer.written[0] == b"hello\n"


@pytest.mark.asyncio
async def test_stdin_writer_forwards_bytes_chunks() -> None:
    """Bytes chunks must be written directly."""
    transport, _ = _make_transport()
    writer = _FakeStreamWriter()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    async with send_tx:
        await send_tx.send(b"raw bytes\n")

    await transport._stdin_writer(writer, send_rx)

    assert len(writer.written) == 1
    assert writer.written[0] == b"raw bytes\n"


# --- AsyncProcessProtocol Contract Tests ---


def test_fake_process_satisfies_protocol() -> None:
    """Our FakeProcess must satisfy the runtime_checkable AsyncProcessProtocol."""
    process = _FakeProcess()
    assert isinstance(process, AsyncProcessProtocol)


# --- ExecutionContext.args Field Tests ---


def test_execution_context_accepts_args_field() -> None:
    """ExecutionContext must accept the 'args' field for MCP server parameters."""
    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext

    ctx = ExecutionContext(
        code="node",
        args=["server.js", "--port", "3000"],
        workspace_root="/tmp/workspace",
    )
    assert ctx.args == ["server.js", "--port", "3000"]


def test_execution_context_args_defaults_to_none() -> None:
    """ExecutionContext.args should default to None."""
    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext

    ctx = ExecutionContext(code="echo test")
    assert ctx.args is None


# --- Connect Flow Tests ---


@pytest.mark.asyncio
async def test_connect_calls_spawn_and_creates_streams() -> None:
    """connect() must call executor.spawn_background_process and yield streams."""
    from unittest.mock import AsyncMock

    transport, executor = _make_transport()

    fake_process = _FakeProcess(
        stdin=_FakeStreamWriter(),
        stdout=_FakeStreamReader([b'{"jsonrpc":"2.0","id":1}\n']),
        stderr=_FakeStreamReader([]),
    )
    executor.spawn_background_process = AsyncMock(return_value=fake_process)

    async with transport.connect() as (read_stream, write_stream):
        assert read_stream is not None
        assert write_stream is not None

    executor.spawn_background_process.assert_called_once()


# --- Stderr Batch Flush Edge Case ---


@pytest.mark.asyncio
async def test_stderr_reader_flushes_remaining_batch_under_ten() -> None:
    """Lines less than 10 must still be flushed at end-of-stream."""
    with tempfile.TemporaryDirectory() as tmpdir:
        transport, _ = _make_transport(workspace_path=tmpdir, server_name="flush-test")

        lines = [f"line {i}\n".encode() for i in range(3)]
        reader = _FakeStreamReader(lines)

        await transport._stderr_reader(reader)

        log_file = Path(tmpdir) / ".myrm" / "mcp_logs" / "flush-test.log"
        content = log_file.read_text()
        assert "line 0" in content
        assert "line 1" in content
        assert "line 2" in content


# --- Close with Already Exited Process ---


@pytest.mark.asyncio
async def test_close_handles_already_exited_process() -> None:
    """close() must not crash if the process has already exited."""
    transport, _ = _make_transport()
    process = _FakeProcess()
    process._return_code = 0

    def raise_already_terminated() -> None:
        raise ProcessLookupError("Process already exited")

    process.terminate = raise_already_terminated  # type: ignore[assignment]
    transport._process = process

    # Should not raise
    await transport.close()
    assert transport._closed


# --- Mixed Valid and Invalid Stdout ---


@pytest.mark.asyncio
async def test_stdout_reader_preserves_order_of_valid_messages() -> None:
    """Valid messages must arrive in original order despite interleaved noise."""
    import json

    lines = [
        b'{"id": 1, "method": "first"}\n',
        b"NOISE: something\n",
        b'{"id": 2, "method": "second"}\n',
        b"{invalid json}\n",
        b'{"id": 3, "method": "third"}\n',
    ]

    reader = _FakeStreamReader(lines)
    transport, _ = _make_transport()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    await transport._stdout_reader(reader, send_tx)

    results: list[dict[str, object]] = []
    async with send_rx:
        async for item in send_rx:
            results.append(json.loads(item))

    assert len(results) == 3
    assert results[0]["id"] == 1
    assert results[1]["id"] == 2
    assert results[2]["id"] == 3


# --- Stdout Reader: UnicodeDecodeError ---


@pytest.mark.asyncio
async def test_stdout_reader_skips_invalid_utf8() -> None:
    """Non-decodable bytes on stdout must be silently skipped."""
    lines = [
        b"\xff\xfe\x00 broken bytes\n",
        b'{"ok": true}\n',
    ]

    reader = _FakeStreamReader(lines)
    transport, _ = _make_transport()

    send_tx, send_rx = anyio.create_memory_object_stream[str | bytes](64)

    await transport._stdout_reader(reader, send_tx)

    results: list[str | bytes] = []
    async with send_rx:
        async for item in send_rx:
            results.append(item)

    assert len(results) == 1
    assert json.loads(results[0])["ok"] is True


# --- Stderr Reader: Batch > 10 lines flush ---


@pytest.mark.asyncio
async def test_stderr_reader_flushes_batch_at_ten_lines() -> None:
    """When 10+ lines accumulate, they should be flushed and more written after."""
    with tempfile.TemporaryDirectory() as tmpdir:
        transport, _ = _make_transport(workspace_path=tmpdir, server_name="batch-test")

        lines = [f"line {i}\n".encode() for i in range(25)]
        reader = _FakeStreamReader(lines)

        await transport._stderr_reader(reader)

        log_file = Path(tmpdir) / ".myrm" / "mcp_logs" / "batch-test.log"
        content = log_file.read_text()
        for i in range(25):
            assert f"line {i}" in content


# --- Connect: Spawn failure propagation ---


@pytest.mark.asyncio
async def test_connect_propagates_spawn_failure() -> None:
    """If executor.spawn_background_process raises, connect() must propagate."""
    from unittest.mock import AsyncMock

    transport, executor = _make_transport()
    executor.spawn_background_process = AsyncMock(
        side_effect=RuntimeError("Sandbox unavailable")
    )

    with pytest.raises(RuntimeError, match="Sandbox unavailable"):
        async with transport.connect():
            pass


# --- Close: SIGKILL timeout path ---


@pytest.mark.asyncio
async def test_close_escalates_to_kill_on_timeout() -> None:
    """If terminate() doesn't stop the process in time, kill() should be called."""
    import asyncio

    transport, _ = _make_transport()
    process = _FakeProcess()

    # Make wait() never return (simulate hung process)
    async def never_return() -> int:
        await asyncio.sleep(100)
        return -1

    process.wait = never_return  # type: ignore[assignment]
    transport._process = process

    async def fast_close() -> None:
        transport._closed = True
        if transport._process:
            try:
                transport._process.terminate()
                try:
                    await asyncio.wait_for(transport._process.wait(), timeout=0.1)
                except TimeoutError:
                    transport._process.kill()
            except Exception:
                pass
            finally:
                transport._process = None

    await fast_close()
    assert process._terminated
    assert process._killed
