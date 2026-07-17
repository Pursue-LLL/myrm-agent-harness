"""Persistent, self-healing MCP session actor — one warm session per server.

Why this exists
---------------
``langchain_mcp_adapters`` builds *connection-based* tools: every ``ainvoke``
opens a fresh ``create_session`` (a new stdio subprocess / SSE connection) and
re-runs the MCP ``initialize`` handshake, then tears it down — the adapter's own
note: "A new session will be created for each tool call". For a server that
loads heavy state on init (a large catalog, a DB pool, a model) this pays the
full startup cost on *every* call and multiplies transient connection failures.

This actor flips that: a single owner task opens the session **once**, keeps it
warm, and serialises all tool calls onto it. Holding an MCP session open is only
anyio-safe when every interaction (enter/exit/initialize/call_tool) runs in the
*same* task, so callers never touch the session directly — they submit a request
and await a future that the owner resolves.

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
- langchain_mcp_adapters.sessions::create_session (POS: MCP transport sessions)
- langchain_mcp_adapters.tools::load_mcp_tools (POS: MCP→LangChain tool loader)
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
MCP persistent-session layer. Owns one warm ClientSession per server and routes
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
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, StructuredTool

from .config import sanitize_mcp_name_component

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

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
        auth_provider: object | None = None,
        oversized_result_handler: object | None = None,
    ) -> None:
        self.server_name = server_name
        self._connection = connection
        self._connect_timeout = connect_timeout
        self._execute_timeout = execute_timeout
        self._max_output_chars = max_output_chars
        self._tool_include = tool_include
        self._tool_exclude = tool_exclude
        self._auth_provider = auth_provider
        self._oversized_result_handler = oversized_result_handler
        # Idle keepalive only matters for remote transports that sit behind LBs /
        # NAT; a local stdio pipe never idle-disconnects (interval 0 = disabled).
        transport = str(connection.get("transport", "")).lower()
        self._keepalive_interval = _KEEPALIVE_INTERVAL if transport in _KEEPALIVE_TRANSPORTS else 0.0

        self._queue: asyncio.Queue[_ToolCall | object] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._start_error: Exception | None = None
        self._closed = False
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
        existing: dict[str, str] = dict(self._connection.get("headers") or {})  # type: ignore[arg-type]
        existing.update(new_headers)
        self._connection["headers"] = existing  # type: ignore[assignment]

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

    # ------------------------------------------------------------ owner task

    async def _run(self) -> None:
        """Owner task: establish the session, serve calls, and self-reconnect.

        Startup is bounded by ``_SESSION_START_MAX_ATTEMPTS`` and either sets the
        ready event (success) or records a start error (give up). In steady
        state the owner serves calls on the warm session; a transport break
        drops into a bounded, backed-off reconnect that rebuilds the session in
        place — the proxy tools handed to the agent keep working across the gap.
        """
        from langchain_mcp_adapters.sessions import create_session
        from langchain_mcp_adapters.tools import load_mcp_tools
        from mcp.types import Implementation

        from myrm_agent_harness import __version__

        conn = dict(self._connection)
        sk = dict(conn.get("session_kwargs") or {})  # type: ignore[arg-type]
        sk["message_handler"] = self._make_notification_handler()
        sk.setdefault("client_info", Implementation(name="myrm-agent", version=__version__))
        conn["session_kwargs"] = sk

        start_attempts = 0
        reconnect_failures = 0
        last_error = "not started"

        while not self._closed:
            # On reconnect, refresh auth headers from the provider so a newly
            # re-authorized token is picked up instead of replaying stale creds.
            if reconnect_failures > 0:
                await self._refresh_auth_headers(conn)
            outcome: _ServeOutcome | None = None
            connected_at = 0.0
            try:
                async with create_session(conn) as session:  # type: ignore[arg-type]
                    async with asyncio.timeout(self._connect_timeout):
                        init_result = await session.initialize()
                        raw_tools = await load_mcp_tools(session, server_name=self.server_name)
                    if not raw_tools:
                        raise _TransientStartError("no tools enumerated")
                    self._apply_tools(init_result, raw_tools)
                    connected_at = time.monotonic()
                    outcome = await self._serve_on(session)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = _describe_error(exc)
                if not self._ready.is_set():
                    start_attempts += 1
                    if start_attempts >= _SESSION_START_MAX_ATTEMPTS:
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

    def _apply_tools(self, init_result: object, raw_tools: list[BaseTool]) -> None:
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
        """Build a ``message_handler`` for ``ClientSession``.

        Dispatches ``ToolListChangedNotification`` into the queue as a refresh
        signal; prompt/resource change notifications are logged for future use.
        """
        try:
            from mcp.types import (
                PromptListChangedNotification,
                ResourceListChangedNotification,
                ServerNotification,
                ToolListChangedNotification,
            )
        except ImportError:
            logger.debug("MCP SDK notification types unavailable; dynamic tool discovery disabled")
            return None

        async def _handler(
            message: object,
        ) -> None:
            try:
                if isinstance(message, Exception):
                    return
                if isinstance(message, ServerNotification):
                    match message.root:
                        case ToolListChangedNotification():
                            logger.info(
                                "MCP server '%s': received tools/list_changed",
                                self.server_name,
                            )
                            self._queue.put_nowait(_REFRESH_SIGNAL)
                        case PromptListChangedNotification():
                            logger.debug(
                                "MCP server '%s': prompts/list_changed (ignored)",
                                self.server_name,
                            )
                        case ResourceListChangedNotification():
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
        from langchain_mcp_adapters.tools import load_mcp_tools

        try:
            old_names = set(self._tools)
            async with asyncio.timeout(self._connect_timeout):
                raw_tools = await load_mcp_tools(
                    session,
                    server_name=self.server_name,  # type: ignore[arg-type]
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
                existing: dict[str, str] = dict(conn.get("headers") or {})  # type: ignore[arg-type]
                existing.update(headers)
                conn["headers"] = existing  # type: ignore[assignment]
                self._connection["headers"] = existing  # type: ignore[assignment]
                logger.info("MCP session '%s' auth headers refreshed for reconnect", self.server_name)
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
        except ImportError:
            raise RuntimeError("MCP SDK not available for resource reading")

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

    def _make_proxy(self, real_tool: BaseTool) -> BaseTool:
        """Build a schema-identical proxy that routes execution through the queue.

        The proxy resolves the executable tool lazily on each call, so after a
        reconnect it automatically targets the rebound, live-session tool — the
        agent's bound proxy object never has to change.
        """
        tool_name = real_tool.name

        async def _proxy(**params: object) -> object:
            return await self.call(tool_name, params)

        coroutine: Callable[..., Awaitable[object]] = _proxy
        return StructuredTool(
            name=tool_name,
            description=real_tool.description,
            args_schema=real_tool.args_schema or {"type": "object", "properties": {}},
            coroutine=coroutine,
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


def _extract_instructions(init_result: object) -> str | None:
    """Pull server instructions from an MCP initialize result (best-effort)."""
    instructions = getattr(init_result, "instructions", None)
    if not instructions:
        server_info = getattr(init_result, "serverInfo", None)
        if server_info is not None:
            instructions = getattr(server_info, "instructions", None)
    return instructions if isinstance(instructions, str) else None
