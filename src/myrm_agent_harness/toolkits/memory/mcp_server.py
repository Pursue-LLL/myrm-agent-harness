"""Facade re-exporting memory mcp_server for backward-compatible harness surface.

[INPUT]
- toolkits.memory.agent_surface.mcp_server::MemoryMCPServer, create_memory_mcp_server,
  reset_request_memory_manager, reset_request_wiki_boundary_enabled,
  set_request_memory_manager, set_request_wiki_boundary_enabled
  (POS: 记忆 MCP 服务端权威实现层)

[OUTPUT]
- The memory MCP server class, factory and request-scoped manager/boundary hooks

[POS]
Compatibility re-export shim. The authoritative implementation lives in
agent_surface/mcp_server.py; this module exists only so legacy import paths keep working
and must not gain logic of its own.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.agent_surface.mcp_server import (
    MemoryMCPServer,
    create_memory_mcp_server,
    reset_request_memory_manager,
    reset_request_wiki_boundary_enabled,
    set_request_memory_manager,
    set_request_wiki_boundary_enabled,
)

__all__ = [
    "MemoryMCPServer",
    "create_memory_mcp_server",
    "reset_request_memory_manager",
    "reset_request_wiki_boundary_enabled",
    "set_request_memory_manager",
    "set_request_wiki_boundary_enabled",
]
