"""MCP tool discovery layer — ``MCPAgent`` is not ``myrm_agent_harness.agent``.

``MCPAgent`` orchestrates multi-server MCP tool fetch/normalize; it does **not** import or
belong to the harness Agent runtime package. See ``toolkits/_ARCH.md`` § Naming disambiguation.

Provides MCP tool fetching capabilities:
- Fetches tools from multiple MCP servers via ``mcp.ClientSession`` (SDK)
- Server-prefix isolation: ``mcp__{server}__{tool}`` naming prevents collisions and permission bypass
- Maintains tool-to-server mapping
- Supports parallel multi-server tool fetching
- Content block coercion: ensures only LLM-safe types (text, image) reach the API — ``file``, ``audio``, and unknown blocks are gracefully degraded to text, preventing 400 errors and session history poisoning
- Content boundary defense: applies ``wrap_untrusted()`` to MCP tool outputs, ensuring third-party server data receives the same 5-layer content boundary protection as all built-in tools
- Upstream fault tolerance: catches adapter-layer exceptions, returning ``redact_sensitive_text``-sanitized error messages instead of crashing
- Auth error detection: catches ``httpx2.HTTPStatusError(401)`` from the MCP transport, returns a clear re-authorization message, and emits ``MCPAuthExpiredEvent``
- Extracts MCP structured_content from artifacts as supplementary text blocks
- Detects ext-apps ``_meta.ui.resourceUri`` and emits MCP App view events via progress_sink

Pure result/post-processing logic lives in sibling modules:
- ``result_processing`` — result normalization, content coercion, output-size guard, content boundary defense, ext-apps metadata
- ``tool_processing`` — tool filtering, description limits, schema sanitization, safety annotations, name prefixing

[INPUT]
- client::MCPClientManager, MCPServerConfigProtocol (POS: MCP client management layer)
- tool_converter::convert_mcp_tools (POS: MCP tool → LangChain BaseTool converter)
- config::parse_mcp_tool_name, sanitize_mcp_name_component, should_register_mcp_tool (POS: MCP configuration, name sanitization, tool name parsing, and per-server tool filter function)
- schema::FlattenMeta, canonicalize_schema_for_cache, flatten_deep_schema, flatten_json_schema, has_dot_keys, nest_flat_arguments, coerce_arguments_by_schema, prepare_mcp_call_arguments (POS: MCP inbound tool schema normalization)
- result_processing::normalize_mcp_result, coerce_content_block, wrap_multimodal_text_blocks, truncate_multimodal_text_blocks, handle_oversized_output, emit_mcp_app_event (POS: MCP tool result normalization)
- tool_processing::apply_tool_filter, enforce_description_limits, sanitize_tools, register_tool_annotations, prefix_tool_names (POS: MCP tool post-processing)
- core.security.tool_registry::MCPAnnotations, SafetyMetadata, register_ptc_safety_metadata (POS: Tool metadata and permission mapping)
- agent.streaming.types::AgentEventType (POS: Framework-agnostic streaming event types)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: Runtime tool progress event sink)
- core.security.detection.content_boundary::wrap_untrusted (POS: 5-layer content boundary defense for MCP tool outputs)
- core.security.redact::redact_sensitive_text (POS: Regex-based secret redaction for API keys, tokens, passwords in exception messages)
- runtime.events::get_event_bus (wired via auth_notify at runtime import)
- runtime.events.system_events::MCPAuthExpiredEvent (published by runtime handler)
- httpx2::HTTPStatusError (POS: HTTP status error for 401 auth detection)

[OUTPUT]
- MCPAgent: MCP tool fetching, server mapping, post-processing chain orchestration, content boundary defense, upstream fault tolerance, auth error detection, ext-apps metadata emission, and oversized output vault spill (via injectable OversizedResultHandler callback)
- OversizedResultHandler: type alias for the vault-spill callback signature

[POS]
MCP tool discovery layer (not harness Agent runtime). Orchestrates multi-server tool discovery with parallel fetching,
server-prefix isolation (mcp__{server}__{tool} naming), per-server tool filtering
(include/exclude whitelist), description truncation, content block coercion
(file/audio/unknown types gracefully degraded to text for LLM API safety),
content boundary defense (wrap_untrusted for all string outputs against prompt injection),
upstream fault tolerance (catches NotImplementedError/ValueError),
auth error detection (httpx2 401 → MCPAuthExpiredEvent + clear re-auth message),
multimodal result normalization (ImageContent passthrough + structured_content
extraction), ext-apps UI metadata detection and SSE event emission, and safety
metadata registration. `process_session_tools()` is the single post-processing
chain shared by persistent-session actors and one-shot enumeration.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    import httpx2

from .client import MCPClientManager, MCPServerConfigProtocol
from .result_processing import OversizedResultHandler
from .structured_tool import SafeStructuredTool
from .tool_processing import (
    apply_tool_filter,
    enforce_description_limits,
    prefix_tool_names,
    register_tool_annotations,
    sanitize_tools,
    wrap_tools_with_timeout,
)

logger = logging.getLogger(__name__)

# Remote SSE/stdio handshakes occasionally drop the initial tool listing
# (empty result or timeout); a bounded retry makes enumeration reliable
# without masking a server that is genuinely tool-less or unreachable.
_TOOL_FETCH_MAX_ATTEMPTS = 3
_TOOL_FETCH_RETRY_BACKOFF = 0.3


class MCPAgent:
    """MCP agent core — provides tool fetching and server mapping."""

    def __init__(self) -> None:
        self._tool_server_mapping: dict[str, str] = {}
        # ``httpx2.AsyncClient`` instances created for headered streamable HTTP
        # enumeration targets. The SDK never closes an injected client, so the
        # owner must: we track them here and close them after enumeration.
        self._pending_http_clients: list[httpx2.AsyncClient] = []

    def _get_tool_id(self, tool: BaseTool) -> str:
        """Get a unique identifier for a tool (name + description hash)."""
        tool_name = getattr(tool, "name", "unknown")
        tool_desc = getattr(tool, "description", "")
        return f"{tool_name}:{hash(tool_desc)}"

    def _store_tool_server_mapping(self, tools: list[BaseTool], server_name: str) -> None:
        """Store tool-to-server name mapping."""
        for tool in tools:
            tool_id = self._get_tool_id(tool)
            self._tool_server_mapping[tool_id] = server_name

    @staticmethod
    def process_session_tools(
        tools: Sequence[BaseTool],
        server_name: str,
        tool_include: list[str] | None,
        tool_exclude: list[str] | None,
        execute_timeout: float,
        max_output_chars: int = 100_000,
        oversized_result_handler: OversizedResultHandler | None = None,
        host_serial: bool = False,
    ) -> list[BaseTool]:
        """Apply the full post-processing chain to tools bound to a live session.

        Single source of truth shared by the persistent-session actor and the
        one-shot enumeration path, so direct and PTC routes get identical
        filtering, schema sanitization, execution timeout, and safety metadata.
        Returns the filtered, in-place-wrapped tool list (timeout(coercion(call))).

        Pipeline order:
        filter (uses original names) → prefix → description limit →
        sanitize (schema) → timeout + output guard (with optional vault spill) → annotations.
        """
        tools = apply_tool_filter(tools, server_name, tool_include, tool_exclude)
        prefix_tool_names(tools, server_name)
        enforce_description_limits(tools)
        sanitize_tools(tools)
        wrap_tools_with_timeout(tools, execute_timeout, max_output_chars, oversized_result_handler)
        register_tool_annotations(tools, server_name, host_serial)
        return tools

    def get_tool_server_name(self, tool: BaseTool) -> str:
        """Get the server name associated with a tool."""
        tool_id = self._get_tool_id(tool)
        return self._tool_server_mapping.get(tool_id, "unknown_server")

    def get_server_name_by_tool_name(self, tool_name: str) -> str:
        """Look up the server name by tool name."""
        for tool_id, server_name in self._tool_server_mapping.items():
            if tool_id.startswith(f"{tool_name}:"):
                return server_name
        return "unknown_server"

    @staticmethod
    def _build_enumeration_target(
        server_config: MCPServerConfigProtocol,
        http_clients: list[httpx2.AsyncClient] | None = None,
    ) -> AbstractAsyncContextManager[tuple[Any, Any]]:
        """Build the transport target for one-shot tool enumeration.

        - SSE: ``sse_client(url, headers=...)`` — SSE transport accepts ``headers``
          directly (no ``http_client`` param).
        - Streamable HTTP with auth headers: ``streamable_http_client(url, http_client=...)``
          — requires an explicit ``httpx2.AsyncClient`` for custom headers. The
          created client is appended to ``http_clients`` (when provided) so the
          caller can close it after enumeration — the SDK never closes an
          injected client.
        - Streamable HTTP without headers: ``streamable_http_client(url)``.
        - stdio: ``stdio_client(StdioServerParameters(...))`` wrapping.

        Every branch returns an async context manager yielding the transport
        stream pair consumed by ``ClientSession``.
        """
        raw_target = MCPClientManager.build_client_target(server_config)

        if isinstance(raw_target, str):
            headers = MCPClientManager.get_headers(server_config)
            transport_type = server_config.type
            if transport_type == "sse":
                from mcp.client.sse import sse_client

                return sse_client(raw_target, headers=headers or None)
            if headers:
                http_client = MCPClientManager.build_streamable_http_client(headers)
                if http_clients is not None:
                    http_clients.append(http_client)
                from mcp.client.streamable_http import streamable_http_client

                return streamable_http_client(raw_target, http_client=http_client)
            from mcp.client.streamable_http import streamable_http_client

            return streamable_http_client(raw_target)

        from mcp.client.stdio import stdio_client

        return stdio_client(raw_target)

    async def _enumerate_server_tools(
        self,
        server_config: MCPServerConfigProtocol,
    ) -> tuple[str, list[SafeStructuredTool], str | None]:
        """Fetch tools from a single MCP server with connection timeout and bounded retry.

        Uses ``mcp.ClientSession`` over the transport built by
        ``_build_enumeration_target`` for a one-shot connect→list_tools→
        disconnect cycle.  Transient enumeration failures (empty listing,
        timeout, connection drop) are retried up to
        ``_TOOL_FETCH_MAX_ATTEMPTS`` times; genuine cancellation is never
        retried.
        """
        from mcp import ClientSession
        from mcp.types import Implementation

        from myrm_agent_harness import __version__

        from .tool_converter import convert_mcp_tools

        server_name = server_config.name
        connect_timeout = server_config.connect_timeout
        last_error = "not found tools"

        for attempt in range(1, _TOOL_FETCH_MAX_ATTEMPTS + 1):
            pending_http_clients: list[httpx2.AsyncClient] = []
            try:
                target = self._build_enumeration_target(server_config, http_clients=pending_http_clients)
                async with target as streams:
                    read, write = streams[0], streams[1]
                    async with ClientSession(
                        read,
                        write,
                        client_info=Implementation(name="myrm-agent", version=__version__),
                    ) as session:
                        await session.initialize()
                        async with asyncio.timeout(connect_timeout):
                            tools = convert_mcp_tools(
                                list((await session.list_tools()).tools),
                                session.call_tool,
                                server_name=server_name,
                            )
                if tools:
                    return server_name, tools, None
                last_error = "not found tools"
            except asyncio.CancelledError as e:
                from .errors import reraise_if_genuine_cancel

                reraise_if_genuine_cancel(e)
                logger.warning("Server %s cancelled by MCP SDK", server_name)
                return server_name, [], "cancelled by SDK"
            except TimeoutError:
                last_error = f"connection timed out after {connect_timeout}s"
                logger.warning(
                    "MCP server '%s' enumeration timed out after %.1fs (attempt %d/%d)",
                    server_name,
                    connect_timeout,
                    attempt,
                    _TOOL_FETCH_MAX_ATTEMPTS,
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "MCP server '%s' enumeration failed (attempt %d/%d): %s",
                    server_name,
                    attempt,
                    _TOOL_FETCH_MAX_ATTEMPTS,
                    e,
                )
            finally:
                await self._close_http_clients(pending_http_clients)

            if attempt < _TOOL_FETCH_MAX_ATTEMPTS:
                await asyncio.sleep(_TOOL_FETCH_RETRY_BACKOFF)

        return server_name, [], last_error

    async def _close_http_clients(self, clients: list[httpx2.AsyncClient]) -> None:
        """Close ``httpx2.AsyncClient`` instances created for enumeration targets.

        The MCP SDK never closes an injected client, so the owner must. Errors
        are swallowed: a failed close must not mask a successful enumeration.
        """
        for http_client in clients:
            with contextlib.suppress(Exception):
                await http_client.aclose()

    async def get_tools(self, mcp_config: Sequence[MCPServerConfigProtocol] | None = None) -> list[BaseTool]:
        """Get all available MCP tools from configured servers.

        Each server gets a one-shot ``mcp.ClientSession`` connection for tool
        enumeration.  Multiple servers are fetched in parallel.
        """
        if not mcp_config:
            return []

        self._tool_server_mapping.clear()
        configs = await MCPClientManager.prepare_server_configs(mcp_config)
        if not configs:
            return []

        all_tools: list[BaseTool] = []

        async def _fetch_and_process(cfg: MCPServerConfigProtocol) -> list[BaseTool]:
            server_name, tools, error = await self._enumerate_server_tools(cfg)
            if error:
                raise RuntimeError(f"Failed to get tools from {server_name}: {error}")
            include = getattr(cfg, "tool_include", None)
            exclude = getattr(cfg, "tool_exclude", None)
            processed: list[BaseTool] = self.process_session_tools(
                tools,
                server_name,
                include,
                exclude,
                cfg.execute_timeout,
                getattr(cfg, "max_output_chars", 100_000),
                host_serial=bool(getattr(cfg, "host_serial", False)),
            )
            self._store_tool_server_mapping(processed, server_name)
            return processed

        server_list = list(configs.values())
        if len(server_list) == 1:
            all_tools = await _fetch_and_process(server_list[0])
        else:
            results = await asyncio.gather(
                *[_fetch_and_process(cfg) for cfg in server_list],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    logger.error("MCP server fetch failed: %s", result)
                    raise result
                all_tools.extend(result)

        return all_tools
