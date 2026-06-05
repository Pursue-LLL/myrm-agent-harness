"""PTC asyncio RPC server.

[INPUT]
- .models::PtcConfig, PtcRpcRequest, PtcRpcResponse (POS: Protocol models)
- .dispatcher::PtcDispatcher (POS: Tool execution delegate)

[OUTPUT]
- PtcRpcServer: Ephemeral UDS/TCP server for a single PTC session

[POS]
Asyncio-based RPC server that listens on a UDS (or TCP on Windows) socket.
Receives tool-call requests from the child process, dispatches them through
the agent middleware chain, and returns results. One server per execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.ptc.models import (
    PtcConfig,
    PtcRpcRequest,
    PtcRpcResponse,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.ptc.dispatcher import (
        PtcDispatcher,
    )

logger = logging.getLogger(__name__)

_HEADER_SIZE = 4  # uint32 big-endian length prefix


class PtcRpcServer:
    """Ephemeral RPC server for one PTC execution session.

    Lifecycle:
        server = PtcRpcServer(config, dispatcher)
        await server.start()
        # ... run child process ...
        await server.stop()
    """

    def __init__(self, config: PtcConfig, dispatcher: PtcDispatcher) -> None:
        self._config = config
        self._dispatcher = dispatcher
        self._server: asyncio.Server | None = None
        self._socket_path: str = ""
        self._tcp_port: int = 0
        self._use_tcp = sys.platform == "win32"
        self._call_count = 0
        self._active_connections: set[asyncio.Task[None]] = set()

    @property
    def socket_path(self) -> str:
        """UDS socket path (empty if TCP mode)."""
        return self._socket_path

    @property
    def tcp_port(self) -> int:
        """TCP port (0 if UDS mode)."""
        return self._tcp_port

    @property
    def call_count(self) -> int:
        """Number of tool calls processed so far."""
        return self._call_count

    @property
    def dispatcher(self) -> PtcDispatcher:
        """The dispatcher handling tool calls."""
        return self._dispatcher

    async def start(self) -> None:
        """Start the RPC server and begin accepting connections."""
        if self._use_tcp:
            self._server = await asyncio.start_server(self._handle_connection, "127.0.0.1", 0)
            sockets = self._server.sockets
            if sockets:
                self._tcp_port = sockets[0].getsockname()[1]
            logger.debug("PTC RPC server listening on TCP port %d", self._tcp_port)
        else:
            socket_dir = Path(tempfile.gettempdir()) / "myrm_ptc"
            socket_dir.mkdir(parents=True, exist_ok=True)
            self._socket_path = str(socket_dir / f"ptc_{os.getpid()}_{id(self)}.sock")
            if Path(self._socket_path).exists():
                Path(self._socket_path).unlink()

            self._server = await asyncio.start_unix_server(self._handle_connection, path=self._socket_path)
            os.chmod(self._socket_path, 0o600)
            logger.debug("PTC RPC server listening on UDS %s", self._socket_path)

    async def stop(self) -> None:
        """Shut down the server and clean up."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for task in self._active_connections:
            task.cancel()
        if self._active_connections:
            await asyncio.gather(*self._active_connections, return_exceptions=True)
        self._active_connections.clear()

        if self._socket_path and Path(self._socket_path).exists():
            with contextlib.suppress(OSError):
                Path(self._socket_path).unlink()

    def get_child_env(self) -> dict[str, str]:
        """Return env vars that the child process needs to connect."""
        env: dict[str, str] = {}
        if self._use_tcp:
            env["_MYRM_PTC_PORT"] = str(self._tcp_port)
        else:
            env["_MYRM_PTC_SOCKET"] = self._socket_path
        env["_MYRM_PTC_TIMEOUT"] = str(self._config.timeout_seconds)
        return env

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single RPC connection (one request per connection)."""
        task = asyncio.current_task()
        if task:
            self._active_connections.add(task)

        try:
            header = await asyncio.wait_for(
                reader.readexactly(_HEADER_SIZE),
                timeout=self._config.timeout_seconds,
            )
            msg_len = struct.unpack("!I", header)[0]

            if msg_len > 10 * 1024 * 1024:  # 10MB sanity limit
                await self._send_response(
                    writer,
                    PtcRpcResponse(error="Request too large"),
                )
                return

            data = await asyncio.wait_for(
                reader.readexactly(msg_len),
                timeout=self._config.timeout_seconds,
            )

            if self._call_count >= self._config.max_tool_calls:
                await self._send_response(
                    writer,
                    PtcRpcResponse(error=f"Tool call limit reached ({self._config.max_tool_calls})"),
                )
                return

            try:
                request = PtcRpcRequest.model_validate_json(data)
            except Exception as e:
                await self._send_response(
                    writer,
                    PtcRpcResponse(error=f"Invalid request: {e}"),
                )
                return

            self._call_count += 1
            response = await self._dispatcher.dispatch(request)
            await self._send_response(writer, response)

        except TimeoutError:
            logger.warning("PTC RPC connection timed out")
            with contextlib.suppress(Exception):
                await self._send_response(
                    writer,
                    PtcRpcResponse(error="Request timed out"),
                )
        except (ConnectionError, asyncio.IncompleteReadError):
            logger.debug("PTC RPC client disconnected")
        except Exception as e:
            logger.error("PTC RPC server error: %s", e, exc_info=True)
            with contextlib.suppress(Exception):
                await self._send_response(
                    writer,
                    PtcRpcResponse(error=f"Internal server error: {type(e).__name__}"),
                )
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            if task:
                self._active_connections.discard(task)

    @staticmethod
    async def _send_response(
        writer: asyncio.StreamWriter,
        response: PtcRpcResponse,
    ) -> None:
        """Serialize and send a response with length prefix."""
        payload = json.dumps(response.model_dump(exclude_none=True)).encode("utf-8")
        header = struct.pack("!I", len(payload))
        writer.write(header + payload)
        await writer.drain()
