"""Facade re-exporting memory mcp_server for backward-compatible harness surface."""

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
