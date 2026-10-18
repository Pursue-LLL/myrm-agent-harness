"""Tool binding, runtime security posture enforcement, dynamic refresh, and proxy creation for MCPSessionActor.

[INPUT]
- agent::MCPAgent (POS: MCP agent layer — shared tool post-processing)
- config::sanitize_mcp_name_component (POS: MCP Configuration — name sanitizer)
- config_scan::scan_mcp_runtime_surface (POS: static/runtime MCP scanners)
- errors::MCPRuntimePostureError (POS: MCP error handling utilities)
- tool_converter::convert_mcp_tools (POS: MCP→LangChain tool converter)

[OUTPUT]
- enforce_actor_runtime_posture: fail-closed runtime posture scanner
- refresh_actor_tools: dynamic tool discovery handler for notifications/tools/list_changed
- resolve_actor_tool: tool lookup with dash/underscore and prefix normalization
- make_actor_proxy_tool: builds schema-identical SafeStructuredTool with transparent cross-TTL rebinding
- check_actor_stdio_security_gates: enforces WorkspaceTrustGate and OSV malware checks before stdio spawn
- build_actor_client_target: builds transport context manager (stdio / sse / streamable_http with TLS & SSRF guard)
- refresh_actor_auth_headers: re-fetches auth headers on reconnect

[POS]
Internal support module for ``session_actor.py``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast

from langchain_core.tools import BaseTool

from .config import sanitize_mcp_name_component
from .structured_tool import SafeStructuredTool

if TYPE_CHECKING:
    from mcp.client._transport import TransportStreams

    from .session_actor import MCPSessionActor

logger = logging.getLogger(__name__)


def enforce_actor_runtime_posture(
    actor: MCPSessionActor,
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
        actor.server_name,
        instructions=instructions,
        tools=surfaces,
    )
    if not result.allow_use:
        actor._security_terminated = True
        raise MCPRuntimePostureError(
            format_mcp_scan_block_message(result),
            server_name=actor.server_name,
        )


async def refresh_actor_tools(actor: MCPSessionActor, session: object) -> None:
    """Re-fetch tools from the server after a ``list_changed`` notification.

    Runs inside the owner task (serialised by the queue), so no locks are
    needed. Updates ``actor._tools`` (execution layer) but leaves
    ``actor._proxy_tools`` frozen (prompt prefix cache stability).
    """
    from .tool_converter import convert_mcp_tools

    try:
        old_names = set(actor._tools)
        async with asyncio.timeout(actor._connect_timeout):
            raw_tools = convert_mcp_tools(
                list((await session.list_tools()).tools),  # type: ignore[attr-defined]
                session.call_tool,  # type: ignore[attr-defined]
                server_name=actor.server_name,
            )
        from .agent import MCPAgent

        processed = MCPAgent.process_session_tools(
            raw_tools,
            actor.server_name,
            actor._tool_include,
            actor._tool_exclude,
            actor._execute_timeout,
            actor._max_output_chars,
            actor._oversized_result_handler,
            actor._host_serial,
        )
        new_names = {tool.name for tool in processed}
        added = new_names - old_names
        if added:
            added_tools = [tool for tool in processed if tool.name in added]
            try:
                actor._enforce_runtime_posture(None, added_tools)
            except Exception as exc:
                from .errors import MCPRuntimePostureError

                if isinstance(exc, MCPRuntimePostureError):
                    logger.warning(
                        "MCP server '%s': runtime posture blocked dynamic tool refresh: %s",
                        actor.server_name,
                        exc,
                    )
                    return
                raise
        actor._tools = {tool.name: tool for tool in processed}
        removed = old_names - new_names
        if added or removed:
            parts: list[str] = []
            if added:
                parts.append(f"added: {', '.join(sorted(added))}")
            if removed:
                parts.append(f"removed: {', '.join(sorted(removed))}")
            logger.warning(
                "MCP server '%s': tools changed dynamically — %s",
                actor.server_name,
                "; ".join(parts),
            )
        else:
            logger.info(
                "MCP server '%s': dynamic refresh — %d tool(s), no changes",
                actor.server_name,
                len(actor._tools),
            )
    except Exception:
        logger.warning(
            "MCP server '%s': dynamic tool refresh failed",
            actor.server_name,
            exc_info=True,
        )


def resolve_actor_tool(actor: MCPSessionActor, tool_name: str) -> BaseTool | None:
    """Resolve a tool by exact name, dash/underscore variant, or prefixed name."""
    tool = actor._tools.get(tool_name)
    if tool is not None:
        return tool
    for variant in (tool_name.replace("-", "_"), tool_name.replace("_", "-")):
        tool = actor._tools.get(variant)
        if tool is not None:
            return tool
    prefix = f"mcp__{sanitize_mcp_name_component(actor.server_name)}__"
    if not tool_name.startswith(prefix):
        prefixed = f"{prefix}{sanitize_mcp_name_component(tool_name)}"
        return actor._tools.get(prefixed)
    return None


def make_actor_proxy_tool(actor: MCPSessionActor, real_tool: BaseTool) -> SafeStructuredTool:
    """Build a schema-identical proxy that routes execution through the actor queue.

    When the original actor has been closed after idle TTL eviction (or exhausted
    its in-place reconnect budget) and was not terminated due to a security
    violation, ``_actor_resolver`` transparently re-acquires a fresh warm actor
    from the connection pool without mutating the bound ``SafeStructuredTool``
    instance or invalidating the LLM prompt cache.
    """
    tool_name = real_tool.name
    current_actor = actor

    async def _proxy(**params: object) -> object:
        nonlocal current_actor
        if not current_actor.is_healthy() and not current_actor._security_terminated:
            resolver = current_actor._actor_resolver
            if resolver is not None:
                rebound = await resolver()
                if rebound is not None and rebound.is_healthy():
                    current_actor = rebound
        return await current_actor.call(tool_name, params)

    return SafeStructuredTool(
        name=tool_name,
        description=real_tool.description,
        args_schema=real_tool.args_schema or {"type": "object", "properties": {}},
        coroutine=_proxy,
        response_format="content",
        metadata=real_tool.metadata,
    )


async def check_actor_stdio_security_gates(actor: MCPSessionActor, conn: dict[str, object]) -> None:
    """Enforce WorkspaceTrustGate and OSV malware checks before spawning stdio MCP servers."""
    if str(conn.get("transport", "stdio")) != "stdio":
        return
    from .security import check_osv_malware
    from .transport import get_workspace_trust_gate

    raw_cwd = conn.get("cwd")
    cwd_val = str(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else None
    raw_plugin_root = conn.get("plugin_root")
    plugin_root_val = str(raw_plugin_root) if isinstance(raw_plugin_root, str) and raw_plugin_root else None

    gate = get_workspace_trust_gate()
    if gate is not None:
        try:
            gate.assert_mcp_spawn_allowed(
                workspace_root=None,
                cwd=cwd_val,
                plugin_root=plugin_root_val,
                trust_level=gate.get_trust_level(),
            )
        except Exception:
            actor._security_terminated = True
            raise

    raw_cmd = conn.get("command")
    raw_args = conn.get("args")
    if isinstance(raw_cmd, str) and raw_cmd:
        advisory = await check_osv_malware(
            raw_cmd,
            [str(a) for a in raw_args] if isinstance(raw_args, list) else None,
            use_cache=True,
        )
        if advisory:
            actor._security_terminated = True
            raise RuntimeError(
                f"MCP security check failed for '{actor.server_name}': Malware advisory detected: {advisory}"
            )


def build_actor_client_target(
    actor: MCPSessionActor, conn: dict[str, object]
) -> AbstractAsyncContextManager[TransportStreams]:
    """Build the transport target for ``mcp.ClientSession`` from the connection config dict."""
    transport = conn.get("transport", "stdio")
    if transport in ("sse", "streamable_http"):
        url = conn.get("url")
        if not url:
            raise ValueError(f"MCP server '{actor.server_name}': HTTP transport requires 'url'")
        url_str = str(url)
        raw_headers = conn.get("headers")
        headers: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
        from .client import MCPClientManager

        has_tls = MCPClientManager.has_custom_tls(conn)
        if transport == "sse":
            from mcp.client.sse import sse_client

            ssl_ctx = MCPClientManager._build_ssl_context_from_dict(actor.server_name, conn) if has_tls else None
            sse_factory = MCPClientManager.build_sse_client_factory(url_str, ssl_context=ssl_ctx)
            return sse_client(url_str, headers=headers or None, httpx_client_factory=sse_factory)
        if headers or has_tls:
            ssl_ctx = MCPClientManager._build_ssl_context_from_dict(actor.server_name, conn) if has_tls else None
            if ssl_ctx is not None:
                http_client = MCPClientManager.build_streamable_http_client(headers, url=url_str, ssl_context=ssl_ctx)
            else:
                http_client = MCPClientManager.build_streamable_http_client(headers, url=url_str)
            actor._http_client = http_client
            from mcp.client.streamable_http import streamable_http_client

            return streamable_http_client(url_str, http_client=http_client)
        from mcp.client.streamable_http import streamable_http_client

        return streamable_http_client(url_str)

    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    from .env_guard import sanitize_mcp_env

    raw_command = conn.get("command")
    raw_args = conn.get("args")
    args_list = raw_args if isinstance(raw_args, list) else []
    env = conn.get("env")
    cwd = conn.get("cwd")

    sanitized_env: dict[str, str] | None = None
    if isinstance(env, dict):
        clean_env, _ = sanitize_mcp_env({str(k): str(v) for k, v in env.items() if v is not None})
        sanitized_env = clean_env if clean_env else None

    return stdio_client(
        StdioServerParameters(
            command=str(raw_command),
            args=[str(a) for a in args_list],
            env=sanitized_env,
            cwd=str(cwd) if cwd else None,
        )
    )


async def refresh_actor_auth_headers(actor: MCPSessionActor, conn: dict[str, object]) -> None:
    """Re-fetch auth headers from the provider and update *conn* in place."""
    if actor._auth_provider is None:
        return
    transport = str(conn.get("transport", "")).lower()
    if transport not in ("sse", "streamable_http"):
        return
    try:
        url = str(conn.get("url", ""))
        headers = await actor._auth_provider.get_auth_headers(actor.server_name, url)
        if headers:
            raw_headers = conn.get("headers")
            existing: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
            existing.update(headers)
            conn["headers"] = cast(dict[str, object], existing)
            actor._connection["headers"] = cast(dict[str, object], existing)
            logger.info("MCP session '%s' auth headers refreshed for reconnect", actor.server_name)
    except Exception:
        logger.debug(
            "Auth header refresh failed for MCP session '%s', proceeding with existing headers",
            actor.server_name,
            exc_info=True,
        )


async def serve_actor_queue(actor: MCPSessionActor, session: object) -> object:
    """Serve queued calls on ``session`` until shutdown or a transport break."""
    import contextlib

    from .session_actor_types import (
        _REFRESH_SIGNAL,
        _SHUTDOWN,
        _ResourceRead,
        _ServeOutcome,
        _ToolCall,
    )

    get_task: asyncio.Task[_ToolCall | object] | None = None
    try:
        while True:
            if get_task is None:
                get_task = asyncio.ensure_future(actor._queue.get())
            if actor._keepalive_interval > 0:
                done, _pending = await asyncio.wait({get_task}, timeout=actor._keepalive_interval)
                if not done:
                    if await actor._keepalive_ok(session):
                        continue
                    return _ServeOutcome.RECONNECT
                item = get_task.result()
            else:
                item = await get_task
            get_task = None

            if item is _SHUTDOWN:
                return _ServeOutcome.SHUTDOWN
            if item is _REFRESH_SIGNAL:
                await actor._refresh_tools(session)
                continue
            if isinstance(item, _ResourceRead):
                if item.future.cancelled():
                    continue
                try:
                    resource_bytes = await actor._read_resource(session, item.uri)
                    if not item.future.done():
                        item.future.set_result(resource_bytes)
                except asyncio.CancelledError:
                    if not item.future.done():
                        item.future.set_exception(
                            RuntimeError(f"MCP session '{actor.server_name}' closed during resource read")
                        )
                    raise
                except (ConnectionError, ProcessLookupError, EOFError, BrokenPipeError) as exc:
                    if not item.future.done():
                        item.future.set_exception(exc)
                    logger.warning(
                        "MCP session '%s' transport broke during resource read; reconnecting: %s",
                        actor.server_name,
                        exc,
                    )
                    return _ServeOutcome.RECONNECT
                except Exception as exc:
                    if not item.future.done():
                        item.future.set_exception(exc)
                continue
            if not isinstance(item, _ToolCall) or item.future.cancelled():
                continue
            try:
                result = await actor._invoke(item.tool_name, item.params)
                if not item.future.done():
                    item.future.set_result(result)
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.set_exception(RuntimeError(f"MCP session '{actor.server_name}' closed during call"))
                raise
            except (ConnectionError, ProcessLookupError, EOFError, BrokenPipeError) as exc:
                if not item.future.done():
                    item.future.set_exception(exc)
                logger.warning(
                    "MCP session '%s' transport broke during call; reconnecting: %s",
                    actor.server_name,
                    exc,
                )
                return _ServeOutcome.RECONNECT
            except Exception as exc:
                if not item.future.done():
                    item.future.set_exception(exc)
    finally:
        if get_task is not None and not get_task.done():
            get_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await get_task
        elif get_task is not None and not get_task.cancelled():
            with contextlib.suppress(Exception):
                actor._queue.put_nowait(get_task.result())
