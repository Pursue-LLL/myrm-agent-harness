"""Persistent, self-healing MCP session actor — one warm session per server.

[INPUT]
- mcp::ClientSession (POS: MCP SDK high-level session client)
- tool_converter::convert_mcp_tools (POS: MCP→LangChain tool converter)
- agent::MCPAgent (POS: MCP agent layer — shared tool post-processing)
- session_actor_types (POS: queue envelopes, error classification, notification/elicitation builders)
- session_actor_tools (POS: runtime posture enforcement, dynamic refresh, proxy tool builder)

[OUTPUT]
- MCPSessionActor: persistent, self-reconnecting per-server session with
  serialised tool calls, resource reads (ext-apps UI), transport-aware keepalive,
  dynamic tool discovery, auth expiry notification, dynamic auth header refresh,
  and transparent cross-TTL proxy rebinding.

[POS]
MCP persistent-session layer. Owns one warm Client per server and routes
all tool calls and resource reads through a single task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast

from langchain_core.tools import BaseTool

from .config import sanitize_mcp_name_component
from .session_actor_tools import (
    build_actor_client_target,
    check_actor_stdio_security_gates,
    enforce_actor_runtime_posture,
    make_actor_proxy_tool,
    refresh_actor_auth_headers,
    refresh_actor_tools,
    resolve_actor_tool,
    serve_actor_queue,
)
from .session_actor_types import (
    _AUTH_ERROR_PATTERN,
    _REFRESH_SIGNAL,
    _SHUTDOWN,
    MCPActorResolver,
    MCPElicitationHandler,
    _describe_error,
    _extract_instructions,
    _is_auth_error,
    _ResourceRead,
    _ServeOutcome,
    _ToolCall,
    _TransientStartError,
    build_elicitation_callback,
    build_notification_handler,
    read_mcp_resource,
)
from .structured_tool import SafeStructuredTool

if TYPE_CHECKING:
    import httpx2
    from mcp.client._transport import TransportStreams

    from .config import MCPAuthProvider
    from .result_processing import OversizedResultHandler

logger = logging.getLogger(__name__)

_SESSION_START_MAX_ATTEMPTS = 3
_SESSION_START_RETRY_BACKOFF = 0.3
# Extra wait beyond the retry budget for the owner task to report readiness before ``start()`` gives up on it.
_SESSION_START_BUDGET_SLACK = 5.0
_CLOSE_TIMEOUT = 5.0
_RECONNECT_MAX_ATTEMPTS = 5
_RECONNECT_BACKOFF_BASE = 0.5
_RECONNECT_BACKOFF_CAP = 8.0
_RECONNECT_RESET_AFTER = 60.0
_KEEPALIVE_INTERVAL = 180.0
_KEEPALIVE_TRANSPORTS = frozenset({"sse", "streamable_http"})
_ELICITATION_DEFAULT_TIMEOUT = 300.0


class MCPSessionActor:
    """Owns one persistent, self-healing MCP session for a single server."""

    def __init__(
        self,
        server_name: str,
        connection: dict[str, object],
        *,
        connect_timeout: float = 15.0,
        execute_timeout: float = 120.0,
        max_output_chars: int = 100_000,
        tool_include: list[str] | None = None,
        tool_exclude: list[str] | None = None,
        host_serial: bool = False,
        keepalive_interval: float | None = None,
        auth_provider: MCPAuthProvider | None = None,
        oversized_result_handler: OversizedResultHandler | None = None,
        elicitation_handler: MCPElicitationHandler | None = None,
        actor_resolver: MCPActorResolver | None = None,
    ) -> None:
        self.server_name = server_name
        self._connection = connection
        self._connect_timeout = connect_timeout
        self._execute_timeout = execute_timeout
        self._max_output_chars = max_output_chars
        self._tool_include = tool_include
        self._tool_exclude = tool_exclude
        self._host_serial = host_serial
        self._auth_provider = auth_provider
        self._oversized_result_handler = oversized_result_handler
        self._elicitation_handler = elicitation_handler
        self._actor_resolver = actor_resolver
        self._security_terminated = False
        transport = str(connection.get("transport", "")).lower()
        remote_keepalive = float(keepalive_interval) if keepalive_interval is not None else _KEEPALIVE_INTERVAL
        self._keepalive_interval = remote_keepalive if transport in _KEEPALIVE_TRANSPORTS else 0.0

        self._queue: asyncio.Queue[_ToolCall | object] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._start_error: Exception | None = None
        self._closed = False
        self._http_client: httpx2.AsyncClient | None = None
        self._last_activity = time.time()
        self._tools: dict[str, BaseTool] = {}
        self._proxy_tools: list[BaseTool] = []
        self._instructions: str | None = None

    @property
    def instructions(self) -> str | None:
        """MCP ``initialize`` instructions captured once at startup."""
        return self._instructions

    @property
    def tools(self) -> list[BaseTool]:
        """Actor-routed proxy tools (carry schemas, execute on the warm session)."""
        return list(self._proxy_tools)

    @property
    def last_activity(self) -> float:
        """Wall-clock time of the most recent tool call (for TTL accounting)."""
        return self._last_activity

    def update_auth_headers(self, new_headers: dict[str, str]) -> None:
        """Hot-update the stored connection auth headers after re-authorization."""
        raw_headers = self._connection.get("headers")
        existing: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
        existing.update(new_headers)
        self._connection["headers"] = cast(dict[str, object], existing)

    def is_healthy(self) -> bool:
        """True when the owner task is alive and the session started cleanly."""
        return not self._closed and self._start_error is None and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Open the session and block until tools are ready (or fail loudly)."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=f"mcp-actor-{self.server_name}")
        self._task.add_done_callback(self._on_owner_done)
        attempts_budget = (self._connect_timeout + _SESSION_START_RETRY_BACKOFF) * _SESSION_START_MAX_ATTEMPTS
        budget = attempts_budget + _SESSION_START_BUDGET_SLACK
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=budget)
        except TimeoutError as exc:
            await self.close()
            raise RuntimeError(f"MCP server '{self.server_name}' did not become ready within {budget:.0f}s") from exc
        if self._start_error is not None:
            await self.close()
            raise self._start_error

    async def call(self, tool_name: str, params: dict[str, object]) -> object:
        """Submit a tool call to the warm session and await its result."""
        if not self.is_healthy():
            raise RuntimeError(f"MCP session for '{self.server_name}' is not healthy (closed or failed)")
        self._last_activity = time.time()
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        await self._queue.put(_ToolCall(tool_name, params, future))
        return await future

    async def read_resource(self, uri: str) -> bytes:
        """Read a resource by URI from the warm session."""
        if not self.is_healthy():
            raise RuntimeError(f"MCP session for '{self.server_name}' is not healthy (closed or failed)")
        self._last_activity = time.time()
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        await self._queue.put(_ResourceRead(uri, future))
        return await future  # type: ignore[return-value]

    async def close(self) -> None:
        """Signal shutdown, await graceful teardown, fail any pending calls."""
        if self._closed:
            return
        self._closed = True
        if self._task is not None and not self._task.done():
            await self._queue.put(_SHUTDOWN)
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=_CLOSE_TIMEOUT)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
        self._fail_pending(RuntimeError(f"MCP session '{self.server_name}' closed"))
        await self._close_http_client()

    async def _close_http_client(self) -> None:
        """Close any ``httpx2.AsyncClient`` created for the current transport."""
        hc = self._http_client
        if hc is not None:
            self._http_client = None
            with contextlib.suppress(Exception):
                await hc.aclose()

    def _build_elicitation_callback(self) -> object | None:
        """Build an ``elicitation_callback`` for ``mcp.ClientSession``."""
        return build_elicitation_callback(
            self.server_name,
            self._elicitation_handler,
            lambda: _ELICITATION_DEFAULT_TIMEOUT,
        )

    async def _check_stdio_security_gates(self, conn: dict[str, object]) -> None:
        await check_actor_stdio_security_gates(self, conn)

    def _build_client_target(self, conn: dict[str, object]) -> AbstractAsyncContextManager[TransportStreams]:
        return build_actor_client_target(self, conn)

    async def _run(self) -> None:
        """Owner task: establish the session, serve calls, and self-reconnect."""
        from mcp import ClientSession
        from mcp.types import Implementation

        from myrm_agent_harness import __version__

        from .tool_converter import convert_mcp_tools

        conn = dict(self._connection)
        start_attempts = 0
        reconnect_failures = 0
        last_error = "not started"

        while not self._closed:
            await self._close_http_client()
            if reconnect_failures > 0:
                await self._refresh_auth_headers(conn)
            outcome: _ServeOutcome | None = None
            connected_at = 0.0
            try:
                await self._check_stdio_security_gates(conn)
                target = self._build_client_target(conn)
                elicitation_cb = self._build_elicitation_callback()
                client_kwargs: dict[str, object] = {
                    "message_handler": self._make_notification_handler(),
                    "client_info": Implementation(name="myrm-agent", version=__version__),
                }
                if elicitation_cb is not None:
                    client_kwargs["elicitation_callback"] = elicitation_cb
                try:
                    async with target as streams:
                        read, write = streams[0], streams[1]
                        async with ClientSession(
                            read,
                            write,
                            **client_kwargs,  # type: ignore[arg-type]
                        ) as client:
                            async with asyncio.timeout(self._connect_timeout):
                                init_result = await client.initialize()
                            async with asyncio.timeout(self._connect_timeout):
                                raw_tools = convert_mcp_tools(
                                    list((await client.list_tools()).tools),
                                    client.call_tool,
                                    server_name=self.server_name,
                                )
                            if not raw_tools:
                                raise _TransientStartError("no tools enumerated")
                            self._apply_tools(client, raw_tools, init_result)
                            connected_at = time.monotonic()
                            outcome = await self._serve_on(client)
                finally:
                    await self._close_http_client()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = _describe_error(exc)
                if not self._ready.is_set():
                    start_attempts += 1
                    if self._security_terminated or start_attempts >= _SESSION_START_MAX_ATTEMPTS:
                        await self._close_http_client()
                        self._fail_to_start(last_error)
                        return
                    logger.warning(
                        "MCP session '%s' start failed (attempt %d/%d): %s",
                        self.server_name,
                        start_attempts,
                        _SESSION_START_MAX_ATTEMPTS,
                        last_error,
                    )
                    await asyncio.sleep(_SESSION_START_RETRY_BACKOFF)
                    continue
                reconnect_failures += 1
                if self._security_terminated or reconnect_failures > _RECONNECT_MAX_ATTEMPTS:
                    await self._close_http_client()
                    self._give_up_reconnecting(last_error)
                    return
                logger.warning(
                    "MCP session '%s' connect failed, reconnecting (%d/%d): %s",
                    self.server_name,
                    reconnect_failures,
                    _RECONNECT_MAX_ATTEMPTS,
                    last_error,
                )
                await asyncio.sleep(self._reconnect_backoff(reconnect_failures))
                continue

            if outcome is _ServeOutcome.SHUTDOWN:
                return
            if time.monotonic() - connected_at >= _RECONNECT_RESET_AFTER:
                reconnect_failures = 0
            reconnect_failures += 1
            if reconnect_failures > _RECONNECT_MAX_ATTEMPTS:
                self._give_up_reconnecting(last_error)
                return
            logger.info(
                "MCP session '%s' transport reset, reconnecting (%d/%d)",
                self.server_name,
                reconnect_failures,
                _RECONNECT_MAX_ATTEMPTS,
            )
            await asyncio.sleep(self._reconnect_backoff(reconnect_failures))

    async def _serve_on(self, session: object) -> _ServeOutcome:
        """Serve queued calls on ``session`` until shutdown or a transport break."""
        return await serve_actor_queue(self, session)  # type: ignore[return-value]

    async def _keepalive_ok(self, session: object) -> bool:
        """Probe an idle remote session with a cheap in-band request."""
        try:
            async with asyncio.timeout(self._connect_timeout):
                await session.list_tools()  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP session '%s' keepalive failed; reconnecting: %s", self.server_name, exc)
            return False
        return True

    def _enforce_runtime_posture(self, instructions: str | None, processed: list[BaseTool]) -> None:
        enforce_actor_runtime_posture(self, instructions, processed)

    def _apply_tools(
        self,
        client: object,
        raw_tools: Sequence[BaseTool],
        init_result: object | None = None,
    ) -> None:
        """Bind freshly enumerated tools to the live session."""
        from .agent import MCPAgent

        processed = MCPAgent.process_session_tools(
            raw_tools,
            self.server_name,
            self._tool_include,
            self._tool_exclude,
            self._execute_timeout,
            self._max_output_chars,
            self._oversized_result_handler,
            self._host_serial,
        )
        instructions: str | None = None
        if not self._ready.is_set():
            instructions = _extract_instructions(init_result)
        self._enforce_runtime_posture(instructions, processed)
        self._tools = {tool.name: tool for tool in processed}
        if not self._ready.is_set():
            self._instructions = instructions
            self._proxy_tools = [self._make_proxy(tool) for tool in processed]
            self._ready.set()

    def _make_notification_handler(self) -> Callable[[object], Awaitable[None]] | None:
        return build_notification_handler(self.server_name, self._queue)

    async def _refresh_tools(self, session: object) -> None:
        await refresh_actor_tools(self, session)

    def _fail_to_start(self, detail: str) -> None:
        """Give up establishing the first session: surface a hard start error."""
        self._start_error = RuntimeError(f"MCP server '{self.server_name}' failed to start: {detail}")
        self._ready.set()
        self._fail_pending(self._start_error)
        self._maybe_emit_auth_expired(detail)

    def _give_up_reconnecting(self, detail: str) -> None:
        """Reconnect budget exhausted: fail queued calls; the pool rebuilds next."""
        logger.error(
            "MCP session '%s' giving up after %d reconnect attempts: %s",
            self.server_name,
            _RECONNECT_MAX_ATTEMPTS,
            detail,
        )
        self._fail_pending(RuntimeError(f"MCP session '{self.server_name}' reconnect exhausted: {detail}"))
        self._maybe_emit_auth_expired(detail)

    def _maybe_emit_auth_expired(self, detail: str) -> None:
        """Notify auth expiry if the failure looks like an auth/token issue."""
        if not _is_auth_error(detail):
            return
        from myrm_agent_harness.toolkits.mcp.auth_notify import notify_mcp_auth_expired

        notify_mcp_auth_expired(self.server_name, detail)

    async def _refresh_auth_headers(self, conn: dict[str, object]) -> None:
        await refresh_actor_auth_headers(self, conn)

    @staticmethod
    def _reconnect_backoff(attempt: int) -> float:
        """Exponential backoff with a cap for the n-th reconnect attempt."""
        return min(_RECONNECT_BACKOFF_BASE * 2.0 ** (attempt - 1), _RECONNECT_BACKOFF_CAP)

    async def _invoke(self, tool_name: str, params: dict[str, object]) -> object:
        tool = self._resolve_tool(tool_name)
        if tool is None:
            raise RuntimeError(f"MCP tool not found: {self.server_name}.{tool_name}. Available: {sorted(self._tools)}")
        return await tool.ainvoke(params)

    async def _read_resource(self, session: object, uri: str) -> bytes:
        return await read_mcp_resource(session, uri, self._connect_timeout)

    def _resolve_tool(self, tool_name: str) -> BaseTool | None:
        return resolve_actor_tool(self, tool_name)

    def _make_proxy(self, real_tool: BaseTool) -> SafeStructuredTool:
        return make_actor_proxy_tool(self, real_tool)

    def _on_owner_done(self, _task: asyncio.Task[None]) -> None:
        """Owner task ended for any reason — drain so no queued call hangs."""
        self._fail_pending(RuntimeError(f"MCP session '{self.server_name}' ended before the call completed"))

    def _fail_pending(self, error: Exception) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if isinstance(item, (_ToolCall, _ResourceRead)) and not item.future.done():
                item.future.set_exception(error)


__all__ = [
    "_AUTH_ERROR_PATTERN",
    "_CLOSE_TIMEOUT",
    "_ELICITATION_DEFAULT_TIMEOUT",
    "_KEEPALIVE_INTERVAL",
    "_KEEPALIVE_TRANSPORTS",
    "_RECONNECT_BACKOFF_BASE",
    "_RECONNECT_BACKOFF_CAP",
    "_RECONNECT_MAX_ATTEMPTS",
    "_RECONNECT_RESET_AFTER",
    "_REFRESH_SIGNAL",
    "_SESSION_START_BUDGET_SLACK",
    "_SESSION_START_MAX_ATTEMPTS",
    "_SESSION_START_RETRY_BACKOFF",
    "_SHUTDOWN",
    "MCPActorResolver",
    "MCPElicitationHandler",
    "MCPSessionActor",
    "_ResourceRead",
    "_ServeOutcome",
    "_ToolCall",
    "_TransientStartError",
    "_describe_error",
    "_extract_instructions",
    "_is_auth_error",
    "sanitize_mcp_name_component",
]
