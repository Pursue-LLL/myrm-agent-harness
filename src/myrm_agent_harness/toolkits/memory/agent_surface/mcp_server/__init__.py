"""Memory MCP Server Adapter.

[INPUT]
- server (POS: MemoryMCPServer and its factory)
- request_context (POS: per-request manager / wiki boundary scoping)

[OUTPUT]
- MemoryMCPServer: MCP server adapter exposing memory tools
- create_memory_mcp_server: Factory function
- set_request_memory_manager / reset_request_memory_manager: Per-request manager scoping
- set_request_wiki_boundary_enabled / reset_request_wiki_boundary_enabled / get_request_wiki_boundary_enabled: Per-request wiki guard flag

[POS]
Facade of the memory MCP adapter package: wraps MemoryManager as an MCP server exposing
memory_recall, memory_list, memory_store and memory_manage to external agents.
"""

from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.request_context import (
    get_request_wiki_boundary_enabled,
    reset_request_memory_manager,
    reset_request_wiki_boundary_enabled,
    set_request_memory_manager,
    set_request_wiki_boundary_enabled,
)
from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server.server import (
    MemoryMCPServer,
    create_memory_mcp_server,
)

__all__ = [
    "MemoryMCPServer",
    "create_memory_mcp_server",
    "get_request_wiki_boundary_enabled",
    "reset_request_memory_manager",
    "reset_request_wiki_boundary_enabled",
    "set_request_memory_manager",
    "set_request_wiki_boundary_enabled",
]
