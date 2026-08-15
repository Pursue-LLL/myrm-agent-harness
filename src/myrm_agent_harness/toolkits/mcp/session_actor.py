"""Persistent, self-healing MCP session actor — one warm session per server.

Why this exists
---------------
A single owner task opens the MCP session **once** via ``mcp.ClientSession``,
keeps it warm, and serialises all tool calls onto it. Callers never touch the
session directly — they submit a request and await a future that the owner
resolves.

Staying warm for a whole agent lifetime means surviving the things that break a
long-lived connection: a crashed subprocess, an SSE/HTTP drop, an idle timeout
on a load balancer. The owner task therefore reconnects in place on a transport
break (rebinding the executable tools to the fresh session while keeping the
agent-facing proxy objects stable) and, for remote transports, sends a periodic
in-band keepalive ping so an idle connection is never silently dropped.

Dynamic tool discovery: when a server sends ``notifications/tools/list_changed``
the actor refreshes the executable tool map in the owner task (serialised via the
queue, zero locks) while leaving the prompt-facing proxy tools frozen — prompt
prefix cache stability is never compromised.

[INPUT]
- mcp::ClientSession (POS: MCP SDK high-level session client)
- tool_converter::convert_mcp_tools (POS: MCP→LangChain tool converter)
- agent::MCPAgent (POS: MCP agent layer — shared tool post-processing)
- config::sanitize_mcp_name_component (POS: MCP Configuration — name sanitizer for prefix fallback)
- config_scan::scan_mcp_runtime_surface (POS: static/runtime MCP scanners)
- errors::MCPRuntimePostureError (POS: MCP error handling utilities)
- runtime.events::get_event_bus (POS: Framework event bus for cross-layer communication)
- runtime.events.system_events::MCPAuthExpiredEvent (POS: System-level event for MCP auth expiry notification)

[OUTPUT]
- MCPSessionActor: persistent, self-reconnecting per-server session with
  serialised tool calls, resource reads (ext-apps UI), transport-aware keepalive,
  dynamic tool discovery, auth expiry notification, and dynamic auth header refresh.

[POS]
MCP persistent-session layer. Owns one warm Client per server and routes
all tool calls and resource reads through a single task, enabling true
process/connection reuse with transparent recovery from transport breaks,
dynamic tool refresh on ``notifications/tools/list_changed``, and dynamic auth
header refresh from ``auth_provider`` on reconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool

from .config import sanitize_mcp_name_component
from .structured_tool import SafeStructuredTool

if TYPE_CHECKING:
    import httpx2

    from .config import MCPAuthProvider
    from .result_processing import OversizedResultHandler

logger = logging.getLogger(__name__)

# Business-layer elicitation callback: async (server_name, message, schema) -> decision.
MCPElicitationHandler = Callable[[str, str, dict[str, object]], Awaitable[str]]

# Establishing a session (spawn + initialize + list) occasionally drops on the
# first try (empty listing, SSE handshake hiccup); a bounded retry makes startup
# reliable without masking a genuinely tool-less or unreachable server.
_SESSION_START_MAX_ATTEMPTS = 3
_SESSION_START_RETRY_BACKOFF = 0.3

# Grace period for the owner task to drain and tear down on close().
_CLOSE_TIMEOUT = 5.0

# After a session is established, a mid-life transport break (subprocess crash,
# SSE/HTTP drop, idle disconnect) is recovered in place: the owner rebuilds the
# session and resumes serving, so the proxy tools handed to the agent never go
# permanently dead. Reconnects are bounded and backed off so a server that is
# genuinely down fails fast to the pool (which then rebuilds as a last resort).
_RECONNECT_MAX_ATTEMPTS = 5
_RECONNECT_BACKOFF_BASE = 0.5
_RECONNECT_BACKOFF_CAP = 8.0
# A session that stayed healthy at least this long before breaking is treated as
# a fresh incident (its reconnect budget is refreshed), so an unrelated blip
# hours later still gets full retries while a crash-loop stays bounded.
_RECONNECT_RESET_AFTER = 60.0

# Remote transports (SSE / streamable HTTP) sit behind LBs / NAT that silently
# drop idle TCP. A periodic in-band ping keeps the warm session alive; stdio is
# a local pipe that never idle-disconnects, so it is left unprobed (interval 0).
_KEEPALIVE_INTERVAL = 180.0
_KEEPALIVE_TRANSPORTS = frozenset({"sse", "streamable_http"})


class _TransientStartError(Exception):
    """Internal marker: a retryable session-establishment failure."""


class _ServeOutcome(Enum):
    """How the serve loop ended, telling the owner task what to do next."""

    SHUTDOWN = "shutdown"
    RECONNECT = "reconnect"


@dataclass(slots=True)
class _ToolCall:
    """A queued tool invocation awaiting execution on the warm session."""

    tool_name: str
    params: dict[str, object]
    future: asyncio.Future[object]


@dataclass(slots=True)
class _ResourceRead:
    """A queued resource read awaiting execution on the warm session."""

    uri: str
    future: asyncio.Future[object]


_SHUTDOWN = object()
_REFRESH_SIGNAL = object()


_ELICITATION_DEFAULT_TIMEOUT = 300.0


class MCPSessionActor:
    """Owns one persistent, self-healing MCP session for a single server.

    The session lives entirely inside ``_run`` (the owner task). Public methods
    only enqueue work and await futures, so no MCP I/O ever crosses task
    boundaries — the one discipline that keeps an open ``anyio``-based session
    safe across many calls. The owner reconnects on a transport break, so the
    actor stays usable for the agent's whole lifetime.

    An optional ``auth_provider`` (MCPAuthProvider protocol) enables dynamic
    auth header refresh on reconnect: when a session breaks and reconnects,
    fresh headers are fetched from the provider so a re-authorized token is
    used instead of replaying stale credentials baked in at initial spawn.

    An optional ``elicitation_handler`` enables MCP elicitation (MRTR
    ``InputRequiredResult``): when a server requests user confirmation
    mid-tool-call, the handler is invoked to collect the decision and the SDK
    resumes the call automatically. Without a handler the SDK's default
    ``ErrorData("Elicitation not supported")`` is used, and the server sees
    the client as non-elicitation-capable.
    """

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
        # Idle keepalive only matters for remote transports that sit behind LBs /
        # NAT; a local stdio pipe never idle-disconnects (interval 0 = disabled).
        transport = str(connection.get("transport", "")).lower()
        remote_keepalive = float(keepalive_interval) if keepalive_interval is not None else _KEEPALIVE_INTERVAL
        self._keepalive_interval = remote_keepalive if transport in _KEEPALIVE_TRANSPORTS else 0.0

        self._queue: asyncio.Queue[_ToolCall | object] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._start_error: Exception | None = None
        self._closed = False
        self._http_client: httpx2.AsyncClient | None = None
        # Wall-clock of the last call; lets the pool's TTL see activity from
        # *both* PTC (via connection.call) and direct-mode tools (which invoke
        # the proxy → actor directly, bypassing the connection's metrics).
        self._last_activity = time.time()

        # Real session-bound tools the owner executes (call_tool runs in-task).
        # Rebuilt on every (re)connect so they always target the live session.
        self._tools: dict[str, BaseTool] = {}
        # Schema-equivalent proxies whose execution is routed back through the
        # queue, so callers in *other* tasks (direct-mode LLM, PTC) stay safe.
        # Frozen on first ready: the agent holds these objects and they feed the
        # prompt prefix, so they must stay identical across reconnects.
        self._proxy_tools: list[BaseTool] = []
        self._instructions: str | None = None

    # ------------------------------------------------------------------ API

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
        """Hot-update the stored connection auth headers after re-authorization.

        Called by the connection manager when the business layer completes a new
        OAuth flow. The next reconnect (or a forced reconnect) will pick up the
        fresh token instead of replaying stale credentials.
        """
        raw_headers = self._connection.get("headers")
        existing: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
        existing.update(new_headers)
        self._connection["headers"] = cast(dict[str, object], existing)

    def is_healthy(self) -> bool:
        """True when the owner task is alive and the session started cleanly.

        Stays True while the owner reconnects after a transport break: callers
        keep queueing and are served once the session is back, rather than being
        rejected for a transient gap.
        """
        return not self._closed and self._start_error is None and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Open the session and block until tools are ready (or fail loudly)."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=f"mcp-actor-{self.server_name}")
        # Guarantee no caller is left awaiting a future forever: whenever the
        # owner task ends (reconnect exhausted, crash, cancellation), every
        # still-queued call is failed deterministically.
        self._task.add_done_callback(self._on_owner_done)
        budget = (self._connect_timeout + _SESSION_START_RETRY_BACKOFF) * _SESSION_START_MAX_ATTEMPTS + 5.0
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
        """Read a resource by URI from the warm session.

        Used by the MCP Apps (ext-apps) host to fetch UI content declared via
        ``_meta.ui.resourceUri`` in tool results.
        """
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

    # ------------------------------------------------------------ owner task

    async def _close_http_client(self) -> None:
        """Close any ``httpx2.AsyncClient`` created for the current transport."""
        hc = self._http_client
        if hc is not None:
            self._http_client = None
            with contextlib.suppress(Exception):
                await hc.aclose()

    def _build_elicitation_callback(self) -> object | None:
        """Build an ``elicitation_callback`` for ``mcp.ClientSession``.

        When ``elicitation_handler`` is provided the callback bridges MCP SDK
        ``ElicitRequest`` events to the business layer (e.g. ApprovalRegistry),
        making elicitation-capable MCP servers fully functional. The handler is
        an async callable ``(server_name, message, schema) -> "accept"|"decline"|"cancel"``
        injected by the business layer via the connection manager.

        Returns ``None`` when no handler is configured — the SDK falls back to
        its default "Elicitation not supported" response and does not advertise
        ``ElicitationCapability`` to the server.
        """
        handler = self._elicitation_handler
        if handler is None:
            return None

        server_name = self.server_name

        async def _elicitation_callback(context: object, params: object) -> object:
            from mcp.types import ElicitResult

            mode = getattr(params, "mode", "form")
            if mode == "url":
                logger.info(
                    "MCP server '%s' requested url-mode elicitation; declining (not supported)",
                    server_name,
                )
                return ElicitResult(action="decline")

            message = getattr(params, "message", "") or f"MCP server '{server_name}' requests confirmation"
            schema = getattr(params, "requested_schema", None) or {}

            try:
                decision = await asyncio.wait_for(
                    handler(server_name, message, schema),
                    timeout=_ELICITATION_DEFAULT_TIMEOUT,
                )
            except TimeoutError:
                logger.warning(
                    "MCP server '%s' elicitation timed out after %ds",
                    server_name,
                    int(_ELICITATION_DEFAULT_TIMEOUT),
                )
                return ElicitResult(action="cancel")
            except Exception as exc:
                logger.error(
                    "MCP server '%s' elicitation handler failed: %s",
                    server_name,
                    exc,
                    exc_info=True,
                )
                return ElicitResult(action="decline")

            if decision == "accept":
                return ElicitResult(action="accept")
            if decision == "decline":
                return ElicitResult(action="decline")
            if decision == "cancel":
                return ElicitResult(action="cancel")
            logger.warning(
                "MCP server '%s' elicitation handler returned unexpected value: %r; declining",
                server_name,
                decision,
            )
            return ElicitResult(action="decline")

        return _elicitation_callback

    def _build_client_target(
        self, conn: dict[str, object]
    ) -> AbstractAsyncContextManager[tuple[Any, Any]]:
        """Build the transport target for ``mcp.ClientSession`` from the connection config dict.

        Returns a proper SDK v2 target:
        - SSE: ``sse_client(url, headers=...)`` — headers passed directly.
        - Streamable HTTP with auth headers: ``streamable_http_client(url, http_client=...)``
          — ``httpx2.AsyncClient`` stored on ``self._http_client`` for explicit cleanup.
        - Streamable HTTP without headers: ``streamable_http_client(url)`` —
          ``ClientSession`` requires an explicit transport context manager.
        - stdio: ``stdio_client(StdioServerParameters(...))`` transport.

        Every branch returns an async context manager yielding the transport
        stream pair consumed by ``ClientSession``.
        """
        transport = conn.get("transport", "stdio")
        if transport in ("sse", "streamable_http"):
            url = conn.get("url")
            if not url:
                raise ValueError(f"MCP server '{self.server_name}': HTTP transport requires 'url'")
            url_str = str(url)
            raw_headers = conn.get("headers")
            headers: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
            if transport == "sse":
                from mcp.client.sse import sse_client

                return sse_client(url_str, headers=headers or None)
            if headers:
                from .client import MCPClientManager

                http_client = MCPClientManager.build_streamable_http_client(headers)
                self._http_client = http_client
                from mcp.client.streamable_http import streamable_http_client

                return streamable_http_client(url_str, http_client=http_client)
            from mcp.client.streamable_http import streamable_http_client

            return streamable_http_client(url_str)

        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        raw_command = conn.get("command")
        raw_args = conn.get("args")
        args_list = raw_args if isinstance(raw_args, list) else []
        env = conn.get("env")

        return stdio_client(
            StdioServerParameters(
                command=str(raw_command),
                args=[str(a) for a in args_list],
                env=cast(dict[str, str] | None, env) if isinstance(env, dict) else None,
            )
        )

    async def _run(self) -> None:
        """Owner task: establish the session, serve calls, and self-reconnect.

        Startup is bounded by ``_SESSION_START_MAX_ATTEMPTS`` and either sets the
        ready event (success) or records a start error (give up). In steady
        state the owner serves calls on the warm session; a transport break
        drops into a bounded, backed-off reconnect that rebuilds the session in
        place — the proxy tools handed to the agent keep working across the gap.

        Resource safety: a ``httpx2.AsyncClient`` created for a headered
        HTTP/SSE transport is owned by ``self._http_client`` and must be closed
        on *every* exit path — including a transport-target build failure that
        allocates the client and then raises before the serve block (and its
        inner ``finally``) is entered. Cleanup points: loop-top (reconnect
        retries), before ``_fail_to_start`` / ``_give_up_reconnecting`` returns
        (terminal failures), the inner ``finally`` (served sessions), and
        ``close()``.
        """
        from mcp import ClientSession
        from mcp.types import Implementation

        from myrm_agent_harness import __version__

        from .tool_converter import convert_mcp_tools

        conn = dict(self._connection)

        start_attempts = 0
        reconnect_failures = 0
        last_error = "not started"

        while not self._closed:
            # Close any transport-level HTTP client left over from a failed
            # previous iteration (e.g. a transport-target build that allocated
            # the client and then raised before the serve block was entered).
            await self._close_http_client()
            if reconnect_failures > 0:
                await self._refresh_auth_headers(conn)
            outcome: _ServeOutcome | None = None
            connected_at = 0.0
            try:
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
                            # ``initialize`` must not hang forever on a server
                            # whose SSE response never completes (the transport
                            # accepts the POST but the stream stalls); bound it
                            # by the same connect budget as tool enumeration so
                            # a stuck handshake fails over to the retry path
                            # instead of blocking the whole owner task.
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
                    if start_attempts >= _SESSION_START_MAX_ATTEMPTS:
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
                if reconnect_failures > _RECONNECT_MAX_ATTEMPTS:
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
            # Transport broke mid-serve. A long-stable session earns a fresh
            # budget so an unrelated blip later is not penalised by old failures.
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
        """Serve queued calls on ``session`` until shutdown or a transport break.

        The single owner task runs this loop, so tool calls and the idle
        keepalive ping are strictly serialised on the session — the discipline
        that keeps an open anyio session safe. The dequeue future is reused
        across keepalive windows so a call landing during a ping is never lost.
        """
        get_task: asyncio.Task[_ToolCall | object] | None = None
        try:
            while True:
                if get_task is None:
                    get_task = asyncio.ensure_future(self._queue.get())
                if self._keepalive_interval > 0:
                    done, _pending = await asyncio.wait({get_task}, timeout=self._keepalive_interval)
                    if not done:
                        if await self._keepalive_ok(session):
                            continue
                        return _ServeOutcome.RECONNECT
                    item = get_task.result()
                else:
                    item = await get_task
                get_task = None

                if item is _SHUTDOWN:
                    return _ServeOutcome.SHUTDOWN
                if item is _REFRESH_SIGNAL:
                    await self._refresh_tools(session)
                    continue
                if isinstance(item, _ResourceRead):
                    if item.future.cancelled():
                        continue
                    try:
                        resource_bytes = await self._read_resource(session, item.uri)
                        if not item.future.done():
                            item.future.set_result(resource_bytes)
                    except asyncio.CancelledError:
                        # Owner task cancelled (close() exceeded its grace window):
                        # fail the caller's future so it never hangs on a session
                        # that is going away, then re-raise to keep cancel semantics.
                        if not item.future.done():
                            item.future.set_exception(
                                RuntimeError(f"MCP session '{self.server_name}' closed during resource read")
                            )
                        raise
                    except (
                        ConnectionError,
                        ProcessLookupError,
                        EOFError,
                        BrokenPipeError,
                    ) as exc:
                        if not item.future.done():
                            item.future.set_exception(exc)
                        logger.warning(
                            "MCP session '%s' transport broke during resource read; reconnecting: %s",
                            self.server_name,
                            exc,
                        )
                        return _ServeOutcome.RECONNECT
                    except Exception as exc:
                        if not item.future.done():
                            item.future.set_exception(exc)
                    continue
                if not isinstance(item, _ToolCall):
                    continue
                if item.future.cancelled():
                    continue
                try:
                    result = await self._invoke(item.tool_name, item.params)
                    if not item.future.done():
                        item.future.set_result(result)
                except asyncio.CancelledError:
                    # Owner task cancelled (close() exceeded its grace window):
                    # fail the caller's future so it never hangs on a session
                    # that is going away, then re-raise to keep cancel semantics.
                    if not item.future.done():
                        item.future.set_exception(RuntimeError(f"MCP session '{self.server_name}' closed during call"))
                    raise
                except (
                    ConnectionError,
                    ProcessLookupError,
                    EOFError,
                    BrokenPipeError,
                ) as exc:
                    if not item.future.done():
                        item.future.set_exception(exc)
                    logger.warning(
                        "MCP session '%s' transport broke during call; reconnecting: %s",
                        self.server_name,
                        exc,
                    )
                    return _ServeOutcome.RECONNECT
                except Exception as exc:
                    if not item.future.done():
                        item.future.set_exception(exc)
        finally:
            # Leaving the loop with a dequeue in flight: cancel an idle waiter,
            # or push back an item already pulled in a keepalive race so the next
            # session serves it instead of orphaning the caller's future.
            if get_task is not None and not get_task.done():
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await get_task
            elif get_task is not None and not get_task.cancelled():
                with contextlib.suppress(Exception):
                    self._queue.put_nowait(get_task.result())

    async def _keepalive_ok(self, session: object) -> bool:
        """Probe an idle remote session with a cheap in-band request.

        Returns False on failure so the owner reconnects before the next real
        call hits a silently-dropped connection.
        """
        try:
            async with asyncio.timeout(self._connect_timeout):
                await session.list_tools()  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "MCP session '%s' keepalive failed; reconnecting: %s",
                self.server_name,
                exc,
            )
            return False
        return True

    def _enforce_runtime_posture(
        self,
        instructions: str | None,
        processed: list[BaseTool],
    ) -> None:
        """Fail closed when MCP instructions, tool names, or tool descriptions are high/critical risk."""
        from .config_scan import (
            MCPRuntimeToolSurface,
            format_mcp_scan_block_message,
            scan_mcp_runtime_surface,
        )
        from .errors import MCPRuntimePostureError

        surfaces = tuple(
            MCPRuntimeToolSurface(
                name=str(tool.name),
                description=str(getattr(tool, "description", "") or ""),
            )
            for tool in processed
        )
        result = scan_mcp_runtime_surface(
            self.server_name,
            instructions=instructions,
            tools=surfaces,
        )
        if not result.allow_use:
            raise MCPRuntimePostureError(
                format_mcp_scan_block_message(result),
                server_name=self.server_name,
            )

    def _apply_tools(
        self,
        client: object,
        raw_tools: Sequence[BaseTool],
        init_result: object | None = None,
    ) -> None:
        """Bind freshly enumerated tools to the live session.

        Runs on every (re)connect so the executable tools always target the
        current session. The proxy list and instructions are frozen on first
        success: the agent holds those proxy objects and they feed the prompt
        prefix, so they must stay byte-identical across reconnects.
        """
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

    def _make_notification_handler(self):
        """Build a ``message_handler`` for ``mcp.ClientSession``.

        In MCP SDK 2.x, notifications are delivered as their concrete types
        (no ``ServerNotification`` RootModel wrapper). Dispatches
        ``ToolListChangedNotification`` into the queue as a refresh signal.
        """
        try:
            from mcp.types import (
                PromptListChangedNotification,
                ResourceListChangedNotification,
                ToolListChangedNotification,
            )
        except ImportError:
            logger.debug("MCP SDK notification types unavailable; dynamic tool discovery disabled")
            return None

        async def _handler(message: object) -> None:
            try:
                if isinstance(message, Exception):
                    return
                if isinstance(message, ToolListChangedNotification):
                    logger.info(
                        "MCP server '%s': received tools/list_changed",
                        self.server_name,
                    )
                    self._queue.put_nowait(_REFRESH_SIGNAL)
                elif isinstance(message, PromptListChangedNotification):
                    logger.debug(
                        "MCP server '%s': prompts/list_changed (ignored)",
                        self.server_name,
                    )
                elif isinstance(message, ResourceListChangedNotification):
                    logger.debug(
                        "MCP server '%s': resources/list_changed (ignored)",
                        self.server_name,
                    )
            except Exception:
                logger.exception("Error in MCP notification handler for '%s'", self.server_name)

        return _handler

    async def _refresh_tools(self, session: object) -> None:
        """Re-fetch tools from the server after a ``list_changed`` notification.

        Runs inside the owner task (serialised by the queue), so no locks are
        needed. Updates ``self._tools`` (execution layer) but leaves
        ``self._proxy_tools`` frozen (prompt prefix cache stability).
        """
        from .tool_converter import convert_mcp_tools

        try:
            old_names = set(self._tools)
            async with asyncio.timeout(self._connect_timeout):
                raw_tools = convert_mcp_tools(
                    list((await session.list_tools()).tools),  # type: ignore[attr-defined]
                    session.call_tool,  # type: ignore[attr-defined]
                    server_name=self.server_name,
                )
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
            new_names = {tool.name for tool in processed}
            added = new_names - old_names
            if added:
                added_tools = [tool for tool in processed if tool.name in added]
                try:
                    self._enforce_runtime_posture(None, added_tools)
                except Exception as exc:
                    from .errors import MCPRuntimePostureError

                    if isinstance(exc, MCPRuntimePostureError):
                        logger.warning(
                            "MCP server '%s': runtime posture blocked dynamic tool refresh: %s",
                            self.server_name,
                            exc,
                        )
                        return
                    raise
            self._tools = {tool.name: tool for tool in processed}
            removed = old_names - new_names
            if added or removed:
                parts: list[str] = []
                if added:
                    parts.append(f"added: {', '.join(sorted(added))}")
                if removed:
                    parts.append(f"removed: {', '.join(sorted(removed))}")
                logger.warning(
                    "MCP server '%s': tools changed dynamically — %s",
                    self.server_name,
                    "; ".join(parts),
                )
            else:
                logger.info(
                    "MCP server '%s': dynamic refresh — %d tool(s), no changes",
                    self.server_name,
                    len(self._tools),
                )
        except Exception:
            logger.warning(
                "MCP server '%s': dynamic tool refresh failed",
                self.server_name,
                exc_info=True,
            )

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
        """Re-fetch auth headers from the provider and update *conn* in place.

        Called before each reconnect attempt so a token refreshed or re-authorized
        via the Settings UI is picked up immediately instead of replaying stale
        credentials baked in at initial spawn.
        """
        if self._auth_provider is None:
            return
        transport = str(conn.get("transport", "")).lower()
        if transport not in ("sse", "streamable_http"):
            return
        try:
            url = str(conn.get("url", ""))
            headers = await self._auth_provider.get_auth_headers(self.server_name, url)
            if headers:
                raw_headers = conn.get("headers")
                existing: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
                existing.update(headers)
                conn["headers"] = cast(dict[str, object], existing)
                self._connection["headers"] = cast(dict[str, object], existing)
                logger.info(
                    "MCP session '%s' auth headers refreshed for reconnect",
                    self.server_name,
                )
        except Exception:
            logger.debug(
                "Auth header refresh failed for MCP session '%s', proceeding with existing headers",
                self.server_name,
                exc_info=True,
            )

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
        """Read a resource from the MCP server via the active session.

        Returns the raw content bytes. Raises if the server does not support
        resources or the URI is not found.
        """
        try:
            from mcp.types import ReadResourceResult
        except ImportError as exc:
            raise RuntimeError("MCP SDK not available for resource reading") from exc

        async with asyncio.timeout(self._connect_timeout):
            result: ReadResourceResult = await session.read_resource(uri)  # type: ignore[attr-defined]
        if not result.contents:
            raise RuntimeError(f"MCP resource '{uri}' returned empty content")
        content = result.contents[0]
        if hasattr(content, "blob") and content.blob:
            import base64

            return base64.b64decode(content.blob)
        if hasattr(content, "text") and content.text:
            return content.text.encode("utf-8")
        raise RuntimeError(f"MCP resource '{uri}' has no text or blob content")

    def _resolve_tool(self, tool_name: str) -> BaseTool | None:
        tool = self._tools.get(tool_name)
        if tool is not None:
            return tool
        for variant in (tool_name.replace("-", "_"), tool_name.replace("_", "-")):
            tool = self._tools.get(variant)
            if tool is not None:
                return tool
        prefix = f"mcp__{sanitize_mcp_name_component(self.server_name)}__"
        if not tool_name.startswith(prefix):
            prefixed = f"{prefix}{sanitize_mcp_name_component(tool_name)}"
            return self._tools.get(prefixed)
        return None

    def _make_proxy(self, real_tool: BaseTool) -> SafeStructuredTool:
        """Build a schema-identical proxy that routes execution through the queue.

        The proxy resolves the executable tool lazily on each call, so after a
        reconnect it automatically targets the rebound, live-session tool — the
        agent's bound proxy object never has to change.
        """
        tool_name = real_tool.name

        async def _proxy(**params: object) -> object:
            return await self.call(tool_name, params)

        return SafeStructuredTool(
            name=tool_name,
            description=real_tool.description,
            args_schema=real_tool.args_schema or {"type": "object", "properties": {}},
            coroutine=_proxy,
            response_format="content",
            metadata=real_tool.metadata,
        )

    def _on_owner_done(self, _task: asyncio.Task[None]) -> None:
        """Owner task ended for any reason — drain so no queued call hangs."""
        self._fail_pending(RuntimeError(f"MCP session '{self.server_name}' ended before the call completed"))

    def _fail_pending(self, error: Exception) -> None:
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(item, (_ToolCall, _ResourceRead)) and not item.future.done():
                item.future.set_exception(error)


_AUTH_ERROR_PATTERN = re.compile(
    r"\b401\b|unauthorized|invalid_token|token.?expired|unauthenticated",
    re.IGNORECASE,
)


def _is_auth_error(detail: str) -> bool:
    """Heuristic: return True if the error description indicates an auth/token failure."""
    return _AUTH_ERROR_PATTERN.search(detail) is not None


def _describe_error(exc: Exception) -> str:
    """One-line cause for logs and start errors (transient marker stays terse)."""
    if isinstance(exc, _TransientStartError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def _extract_instructions(client_or_result: object) -> str | None:
    """Pull server instructions from an MCP Client or result object."""
    instructions = getattr(client_or_result, "instructions", None)
    if not instructions:
        server_info = getattr(client_or_result, "server_info", None)
        if server_info is not None:
            instructions = getattr(server_info, "instructions", None)
    return instructions if isinstance(instructions, str) else None
