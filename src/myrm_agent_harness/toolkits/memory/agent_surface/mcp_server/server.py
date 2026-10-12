"""Memory MCP server adapter.

[INPUT]
- toolkits.memory.agent_surface.mcp_server.recall_tool::register_recall_tool (POS: Read plane of the MCP adapter)
- toolkits.memory.agent_surface.mcp_server.list_tool::register_list_tool (POS: Browsing counterpart of memory_recall for auditing and cleanup)
- toolkits.memory.agent_surface.mcp_server.store_tool::register_store_tool (POS: Write plane (create) of the MCP adapter)
- toolkits.memory.agent_surface.mcp_server.manage_tool::register_manage_tool (POS: Write plane (modify / remove) of the MCP adapter)
- toolkits.memory.agent_surface.mcp_server.request_context::get_request_memory_manager (POS: ContextVar bindings for per-request scoping)
- toolkits.memory.agent_surface._memory_agent_tool_descriptions (POS: LLM-visible memory tool description SSOT)
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager)

[OUTPUT]
- MemoryMCPServer: MCP server adapter exposing memory tools
- create_memory_mcp_server: Factory function

[POS]
MCP server adapter that lets external AI agents (Claude Code, Cursor, Codex) access the memory system
via the standard MCP protocol by wrapping MemoryManager. Four tools: recall (semantic search with
categories/time/profile), list (enumeration and audit), store (5 categories) and manage
(update/delete/correct/rate). `memory_store` and `memory_manage` descriptions come from the
`_memory_agent_tool_descriptions` SSOT with `surface="mcp"`; recall/list descriptions are MCP-specific.
Supports an optional manager_resolver for per-request dynamic scoping (e.g. per-token agent binding).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from myrm_agent_harness.toolkits.memory.agent_surface._memory_agent_tool_descriptions import (
    build_mcp_memory_store_tool_description,
    resolve_memory_manage_tool_description,
)
from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.list_tool import register_list_tool
from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.manage_tool import register_manage_tool
from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.recall_tool import register_recall_tool
from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.request_context import get_request_memory_manager
from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.store_tool import register_store_tool

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

_INSTRUCTIONS = (
    "Memory service for storing, recalling, listing, and managing user "
    "knowledge, preferences, and project context. Use memory_recall to "
    "search by query. Use memory_list to browse or audit memories by "
    "category. Use memory_store to save important facts. Use "
    "memory_manage to correct, rate, update, or delete memories."
)


class MemoryMCPServer:
    """MCP server adapter exposing MemoryManager as MCP tools.

    Provides memory_recall, memory_list, memory_store, and memory_manage
    tools that external agents can invoke via MCP protocol.

    Supports two modes:
    - Fixed: a single MemoryManager bound at construction.
    - Resolver: a callable that returns the MemoryManager for the current
      request context (e.g. per-token agent scoping via ContextVar).

    Usage:
        # Fixed mode
        mcp_server = MemoryMCPServer(manager)

        # Resolver mode (multi-scope)
        mcp_server = MemoryMCPServer(manager, manager_resolver=my_resolver)
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        server_name: str = "myrm-memory",
        manager_resolver: Callable[[], MemoryManager] | None = None,
        stateless_http: bool = False,
    ) -> None:
        self._default_manager = memory_manager
        self._manager_resolver = manager_resolver
        self._stateless_http = stateless_http
        self._mcp = MCPServer(server_name, instructions=_INSTRUCTIONS)
        register_recall_tool(self._mcp, self._resolve_manager)
        register_list_tool(self._mcp, self._resolve_manager)
        register_store_tool(
            self._mcp,
            self._resolve_manager,
            description=build_mcp_memory_store_tool_description(
                approval_required=memory_manager.approval_required,
            ),
        )
        register_manage_tool(
            self._mcp,
            self._resolve_manager,
            description=resolve_memory_manage_tool_description(surface="mcp"),
        )

    def _resolve_manager(self) -> MemoryManager:
        """Return the active MemoryManager for the current request context."""
        bound = get_request_memory_manager()
        if bound is not None:
            return bound
        if self._manager_resolver is not None:
            return self._manager_resolver()
        return self._default_manager

    @property
    def mcp(self) -> MCPServer:
        """Access the underlying MCPServer instance for advanced configuration."""
        return self._mcp

    def get_streamable_http_app(
        self,
        stateless: bool | None = None,
        streamable_http_path: str | None = None,
        transport_security: TransportSecuritySettings | None = None,
    ) -> Starlette:
        """Get a Starlette/ASGI app for Streamable HTTP transport.

        The stateless mode can be configured via ``stateless_http`` at init or
        overridden via ``stateless`` here. When enabled, each request creates a
        fresh transport with no session tracking (no ``Mcp-Session-Id``),
        appropriate when tools are inherently per-request (e.g. auth via Bearer
        token + ContextVar scoping) and no cross-request session state is needed.

        Mount this on your FastAPI application:
            app.mount("/mcp", mcp_server.get_streamable_http_app())
        """
        build_app = partial(
            self._mcp.streamable_http_app,
            stateless_http=self._stateless_http if stateless is None else stateless,
            json_response=True,
            transport_security=transport_security,
        )
        if streamable_http_path is None:
            return build_app()
        return build_app(streamable_http_path=streamable_http_path)


def create_memory_mcp_server(
    memory_manager: MemoryManager,
    *,
    server_name: str = "myrm-memory",
    manager_resolver: Callable[[], MemoryManager] | None = None,
) -> MemoryMCPServer:
    """Factory: create a MemoryMCPServer from a MemoryManager instance.

    Args:
        memory_manager: The default MemoryManager to expose via MCP.
        server_name: MCP server name visible to external agents.
        manager_resolver: Optional callable returning the MemoryManager for the
            current request context. When provided, tool calls resolve the
            manager dynamically (e.g. per-token agent scoping).

    Returns:
        Configured MemoryMCPServer ready to be mounted.
    """
    return MemoryMCPServer(
        memory_manager,
        server_name=server_name,
        manager_resolver=manager_resolver,
    )
