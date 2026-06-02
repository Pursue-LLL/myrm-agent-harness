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

[OUTPUT]
- MCPSessionActor: persistent, self-reconnecting per-server session with
  serialised tool calls, transport-aware keepalive, and dynamic tool discovery.

[POS]
MCP persistent-session layer. Owns one warm ClientSession per server and routes
all tool calls through a single task, enabling true process/connection reuse
with transparent recovery from transport breaks and dynamic tool refresh on
``notifications/tools/list_changed``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
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


_SHUTDOWN = object()
_REFRESH_SIGNAL = object()


class MCPSessionActor:
    """Owns one persistent, self-healing MCP session for a single server.

    The session lives entirely inside ``_run`` (the owner task). Public methods
    only enqueue work and await futures, so no MCP I/O ever crosses task
    boundaries — the one discipline that keeps an open ``anyio``-based session
    safe across many calls. The owner reconnects on a transport break, so the
    actor stays usable for the agent's whole lifetime.
    """

    def __init__(
        self,
        server_name: str,
        connection: dict[str, object],
        *,
        connect_timeout: float = 15.0,
        execute_timeout: float = 120.0,
        tool_include: list[str] | None = None,
        tool_exclude: list[str] | None = None,
    ) -> None:
        self.server_name = server_name
        self._connection = connection
        self._connect_timeout = connect_timeout
        self._execute_timeout = execute_timeout
        self._tool_include = tool_include
        self._tool_exclude = tool_exclude
        # Idle keepalive only matters for remote transports that sit behind LBs /
        # NAT; a local stdio pipe never idle-disconnects (interval 0 = disabled).
        transport = str(connection.get("transport", "")).lower()
        self._keepalive_interval = (
            _KEEPALIVE_INTERVAL if transport in _KEEPALIVE_TRANSPORTS else 0.0
        )

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

    def is_healthy(self) -> bool:
        """True when the owner task is alive and the session started cleanly.

        Stays True while the owner reconnects after a transport break: callers
        keep queueing and are served once the session is back, rather than being
        rejected for a transient gap.
        """
        return (
            not self._closed
            and self._start_error is None
            and self._task is not None
            and not self._task.done()
        )

    async def start(self) -> None:
        """Open the session and block until tools are ready (or fail loudly)."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run(), name=f"mcp-actor-{self.server_name}"
        )
        # Guarantee no caller is left awaiting a future forever: whenever the
        # owner task ends (reconnect exhausted, crash, cancellation), every
        # still-queued call is failed deterministically.
        self._task.add_done_callback(self._on_owner_done)
        budget = (
            (self._connect_timeout + _SESSION_START_RETRY_BACKOFF)
            * _SESSION_START_MAX_ATTEMPTS
            + 5.0
        )
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=budget)
        except TimeoutError as exc:
            await self.close()
            raise RuntimeError(
                f"MCP server '{self.server_name}' did not become ready within {budget:.0f}s"
            ) from exc
        if self._start_error is not None:
            await self.close()
            raise self._start_error

    async def call(self, tool_name: str, params: dict[str, object]) -> object:
        """Submit a tool call to the warm session and await its result."""
        if not self.is_healthy():
            raise RuntimeError(
                f"MCP session for '{self.server_name}' is not healthy (closed or failed)"
            )
        self._last_activity = time.time()
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        await self._queue.put(_ToolCall(tool_name, params, future))
        return await future

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

        conn = dict(self._connection)
        sk = dict(conn.get("session_kwargs") or {})  # type: ignore[arg-type]
        sk["message_handler"] = self._make_notification_handler()
        conn["session_kwargs"] = sk

        start_attempts = 0
        reconnect_failures = 0
        last_error = "not started"

        while not self._closed:
            outcome: _ServeOutcome | None = None
            connected_at = 0.0
            try:
                async with create_session(conn) as session:  # type: ignore[arg-type]
                    async with asyncio.timeout(self._connect_timeout):
                        init_result = await session.initialize()
                        raw_tools = await load_mcp_tools(
                            session, server_name=self.server_name
                        )
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
                    done, _pending = await asyncio.wait(
                        {get_task}, timeout=self._keepalive_interval
                    )
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
        )
        self._tools = {tool.name: tool for tool in processed}
        if not self._ready.is_set():
            self._instructions = _extract_instructions(init_result)
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
                logger.exception(
                    "Error in MCP notification handler for '%s'", self.server_name
                )

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
                    session, server_name=self.server_name  # type: ignore[arg-type]
                )
            from .agent import MCPAgent

            processed = MCPAgent.process_session_tools(
                raw_tools,
                self.server_name,
                self._tool_include,
                self._tool_exclude,
                self._execute_timeout,
            )
            self._tools = {tool.name: tool for tool in processed}
            new_names = set(self._tools)
            added = new_names - old_names
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
        self._start_error = RuntimeError(
            f"MCP server '{self.server_name}' failed to start: {detail}"
        )
        self._ready.set()
        self._fail_pending(self._start_error)

    def _give_up_reconnecting(self, detail: str) -> None:
        """Reconnect budget exhausted: fail queued calls; the pool rebuilds next."""
        logger.error(
            "MCP session '%s' giving up after %d reconnect attempts: %s",
            self.server_name,
            _RECONNECT_MAX_ATTEMPTS,
            detail,
        )
        self._fail_pending(
            RuntimeError(
                f"MCP session '{self.server_name}' reconnect exhausted: {detail}"
            )
        )

    @staticmethod
    def _reconnect_backoff(attempt: int) -> float:
        """Exponential backoff with a cap for the n-th reconnect attempt."""
        return min(
            _RECONNECT_BACKOFF_BASE * 2.0 ** (attempt - 1), _RECONNECT_BACKOFF_CAP
        )

    async def _invoke(self, tool_name: str, params: dict[str, object]) -> object:
        tool = self._resolve_tool(tool_name)
        if tool is None:
            raise RuntimeError(
                f"MCP tool not found: {self.server_name}.{tool_name}. "
                f"Available: {sorted(self._tools)}"
            )
        return await tool.ainvoke(params)

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
        self._fail_pending(
            RuntimeError(
                f"MCP session '{self.server_name}' ended before the call completed"
            )
        )

    def _fail_pending(self, error: Exception) -> None:
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(item, _ToolCall) and not item.future.done():
                item.future.set_exception(error)


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
