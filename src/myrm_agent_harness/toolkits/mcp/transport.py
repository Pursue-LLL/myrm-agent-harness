"""Executor-backed MCP Stdio Transport.

Bridges the MCP SDK's anyio streams with our CodeExecutor's AsyncProcessProtocol.
Provides critical security and stability features for SaaS environments:
1. Nested Sandboxing: Runs MCP servers via CodeExecutor (bwrap/docker).
2. Noisy Stdout Filtering: Silently drops non-JSON lines to prevent parser crashes.
3. Stderr Draining: Asynchronously reads stderr to prevent OS pipe deadlocks,
   and logs errors to a user-accessible file in the workspace.
4. Zombie Process Prevention: Robust termination sequence (SIGTERM -> SIGKILL).

[INPUT]
- toolkits.code_execution.executors.base::CodeExecutor, (POS: Code executor base classes.)
- toolkits.code_execution.executors.models::AsyncProcessProtocol (POS: Data models for code execution.)

[OUTPUT]
- ExecutorStdioTransport: A transport that runs an MCP server via a CodeExecutor.

[POS]
Executor-backed MCP Stdio Transport.
"""

import asyncio
import logging
import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.client.stdio import StdioServerParameters

from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor, ExecutionContext
from myrm_agent_harness.toolkits.code_execution.executors.models import AsyncProcessProtocol

logger = logging.getLogger(__name__)


class ExecutorStdioTransport:
    """A transport that runs an MCP server via a CodeExecutor."""

    def __init__(
        self,
        executor: CodeExecutor,
        server_name: str,
        parameters: StdioServerParameters,
        allow_network: bool = False,
        max_memory_mb: int = 2048,
    ):
        self.executor = executor
        self.server_name = server_name
        self.parameters = parameters
        self.allow_network = allow_network
        self.max_memory_mb = max_memory_mb

        self._process: AsyncProcessProtocol | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._closed = False

    async def _stdin_writer(
        self, process_stdin: asyncio.StreamWriter, receive_stream: MemoryObjectReceiveStream[str | bytes]
    ) -> None:
        """Read from anyio stream and write to process stdin."""
        try:
            async with receive_stream:
                async for chunk in receive_stream:
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    process_stdin.write(chunk)
                    await process_stdin.drain()
        except (asyncio.CancelledError, BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            logger.warning(f"[MCP Transport {self.server_name}] Error in stdin writer: {e}")
        finally:
            with suppress(Exception):
                process_stdin.close()

    async def _stdout_reader(
        self, process_stdout: asyncio.StreamReader, send_stream: MemoryObjectSendStream[str | bytes]
    ) -> None:
        """Read from process stdout, filter noisy lines, and write to anyio stream."""
        import json

        try:
            async with send_stream:
                while True:
                    line = await process_stdout.readline()
                    if not line:
                        break

                    try:
                        decoded_line = line.decode("utf-8")
                    except UnicodeDecodeError:
                        continue

                    # Noisy Stdout Filter: Only pass lines that look like JSON-RPC
                    stripped = decoded_line.strip()
                    if not stripped:
                        continue

                    # Fast path: check if it starts with { or [
                    if not (stripped.startswith("{") or stripped.startswith("[")):
                        logger.debug(f"[MCP Transport {self.server_name}] Dropped noisy stdout: {stripped}")
                        continue

                    # Strict path: check if it's valid JSON to prevent parser crashes
                    try:
                        json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.debug(f"[MCP Transport {self.server_name}] Dropped invalid JSON stdout: {stripped}")
                        continue

                    await send_stream.send(decoded_line)
        except (asyncio.CancelledError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass
        except Exception as e:
            logger.warning(f"[MCP Transport {self.server_name}] Error in stdout reader: {e}")

    _MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

    async def _stderr_reader(self, process_stderr: asyncio.StreamReader) -> None:
        """Drain stderr to prevent pipe deadlocks and log to workspace.

        Includes lightweight log rotation: when the file exceeds 5 MB,
        it is truncated to keep only the most recent half, preventing
        unbounded disk growth in long-running SaaS sandboxes.
        """
        import os
        from pathlib import Path

        import aiofiles

        log_dir = Path(self.executor.workspace_path) / ".myrm" / "mcp_logs"
        log_file = log_dir / f"{self.server_name}.log"

        try:
            os.makedirs(str(log_dir), exist_ok=True)

            batch: list[str] = []
            writes_since_size_check = 0

            async with aiofiles.open(str(log_file), mode="a", encoding="utf-8") as f:
                while True:
                    line = await process_stderr.readline()
                    if not line:
                        break

                    try:
                        decoded = line.decode("utf-8").strip()
                        if decoded:
                            batch.append(decoded)
                            logger.debug(f"[MCP {self.server_name} STDERR] {decoded}")

                            if len(batch) >= 10:
                                content = "\n".join(batch) + "\n"
                                await f.write(content)
                                await f.flush()
                                batch.clear()
                                writes_since_size_check += 1

                                # Check file size every ~50 flushes (~500 lines)
                                if writes_since_size_check >= 50:
                                    writes_since_size_check = 0
                                    await self._rotate_if_needed(log_file)
                    except UnicodeDecodeError:
                        pass

                if batch:
                    content = "\n".join(batch) + "\n"
                    await f.write(content)
                    await f.flush()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[MCP Transport {self.server_name}] Error in stderr reader: {e}")

    @staticmethod
    async def _rotate_if_needed(log_file: "pathlib.Path") -> None:
        """Truncate the log file if it exceeds the size limit, keeping the tail."""
        import os

        import aiofiles

        try:
            size = os.path.getsize(str(log_file))
            if size <= ExecutorStdioTransport._MAX_LOG_SIZE_BYTES:
                return

            # Keep the last half of the file (most recent logs)
            keep_bytes = size // 2
            async with aiofiles.open(str(log_file), mode="rb") as rf:
                await rf.seek(size - keep_bytes)
                # Advance to the next full line to avoid a partial first line
                await rf.readline()
                tail = await rf.read()

            async with aiofiles.open(str(log_file), mode="wb") as wf:
                await wf.write(tail)

            logger.info(f"[MCP Log Rotation] Truncated {log_file.name}: {size} -> {len(tail)} bytes")
        except Exception as e:
            logger.debug(f"[MCP Log Rotation] Skipped: {e}")

    @asynccontextmanager
    async def connect(
        self,
    ) -> AsyncIterator[
        tuple[
            MemoryObjectReceiveStream[str | bytes],
            MemoryObjectSendStream[str | bytes],
        ]
    ]:
        """Connect to the MCP server and return the read/write streams."""
        if self._closed:
            raise RuntimeError("Transport is closed")

        cwd = getattr(self.parameters, "cwd", None)
        work_dir = str(cwd) if cwd else "/workspace"

        # Prepare execution context
        context = ExecutionContext(
            code=self.parameters.command,
            args=list(self.parameters.args) if self.parameters.args else None,
            env=(dict(self.parameters.env) if self.parameters.env is not None else None),
            allow_network=self.allow_network,
            max_memory_mb=self.max_memory_mb,
            workspace_root=self.executor.workspace_path,
            work_dir=work_dir,
        )

        # OSV malware check before spawning
        from myrm_agent_harness.toolkits.mcp.security import check_osv_malware

        advisory = await check_osv_malware(
            self.parameters.command,
            list(self.parameters.args) if self.parameters.args else None,
        )
        if advisory:
            raise RuntimeError(
                f"[MCP Transport {self.server_name}] Malware advisory detected: {advisory}"
            )

        try:
            self._process = await self.executor.spawn_background_process(context)
            logger.info(f"[MCP Transport {self.server_name}] Started process via executor")
        except Exception as e:
            logger.error(f"[MCP Transport {self.server_name}] Failed to spawn process: {e}")
            raise

        # Create anyio memory streams for the SDK to interact with
        # SDK reads from read_stream_rx, we write to read_stream_tx
        # SDK writes to write_stream_tx, we read from write_stream_rx
        read_stream_tx, read_stream_rx = anyio.create_memory_object_stream(256)
        write_stream_tx, write_stream_rx = anyio.create_memory_object_stream(256)

        # Start bridge tasks
        # Note: We must cast the streams to the expected types since AsyncProcessProtocol
        # returns `object` to remain agnostic, but we know they are asyncio streams here.
        stdin_writer = asyncio.create_task(
            self._stdin_writer(self._process.stdin, write_stream_rx)  # type: ignore
        )
        stdout_reader = asyncio.create_task(
            self._stdout_reader(self._process.stdout, read_stream_tx)  # type: ignore
        )
        stderr_reader = asyncio.create_task(
            self._stderr_reader(self._process.stderr)  # type: ignore
        )

        self._tasks.extend([stdin_writer, stdout_reader, stderr_reader])

        try:
            # Yield the streams to the MCP SDK
            yield read_stream_rx, write_stream_tx
        finally:
            await self.close()

    async def close(self) -> None:
        """Close the transport and terminate the process."""
        if self._closed:
            return
        self._closed = True

        logger.info(f"[MCP Transport {self.server_name}] Closing transport")

        # Cancel bridge tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        # Terminate process robustly
        if self._process:
            try:
                self._process.terminate()

                # Wait up to 3 seconds for graceful shutdown
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=3.0)
                except TimeoutError:
                    logger.warning(f"[MCP Transport {self.server_name}] Process did not terminate, sending SIGKILL")
                    self._process.kill()
                    await self._process.wait()
            except Exception as e:
                logger.warning(f"[MCP Transport {self.server_name}] Error during process termination: {e}")
            finally:
                self._process = None
