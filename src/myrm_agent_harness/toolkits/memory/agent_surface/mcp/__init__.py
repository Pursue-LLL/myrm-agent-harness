"""Public entry point for ai-memory wire interoperability and MCP server gateway.

Exposes drop-in wire-compatible tools and MCP server factory for external agents
(Claude Code, Cursor, Codex).
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.agent_surface.mcp.ai_memory_wire_adapter::AiMemoryWireAdapter (POS: Wire-format adapter
  emulating the 5.3k Star ai-memory MCP tool protocol.)
- toolkits.memory.agent_surface.mcp.server_factory::create_interop_memory_mcp_server (POS: Server factory
  creating standard MCP server with ai-memory wire parity.)
- toolkits.memory.agent_surface.mcp.types::AiMemoryFinalizeRequest, AiMemoryFinalizeResult,
  AiMemoryQueryRequest, AiMemoryQueryResult, AiMemoryRememberRequest, AiMemoryRememberResult, McpServerInfo
  (POS: Data models for ai-memory wire format interoperability and cross-tool MCP gateway.)

[OUTPUT]
- Package facade re-exporting 9 public names: AiMemoryFinalizeRequest, AiMemoryFinalizeResult,
  AiMemoryQueryRequest, AiMemoryQueryResult, AiMemoryRememberRequest, AiMemoryRememberResult,
  AiMemoryWireAdapter, McpServerInfo, create_interop_memory_mcp_server

[POS]
Public entry point for ai-memory wire interoperability and MCP server gateway.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.agent_surface.mcp.ai_memory_wire_adapter import (
    AiMemoryWireAdapter,
)
from myrm_agent_harness.toolkits.memory.agent_surface.mcp.server_factory import (
    create_interop_memory_mcp_server,
)
from myrm_agent_harness.toolkits.memory.agent_surface.mcp.types import (
    AiMemoryFinalizeRequest,
    AiMemoryFinalizeResult,
    AiMemoryQueryRequest,
    AiMemoryQueryResult,
    AiMemoryRememberRequest,
    AiMemoryRememberResult,
    McpServerInfo,
)

__all__ = [
    "AiMemoryFinalizeRequest",
    "AiMemoryFinalizeResult",
    "AiMemoryQueryRequest",
    "AiMemoryQueryResult",
    "AiMemoryRememberRequest",
    "AiMemoryRememberResult",
    "AiMemoryWireAdapter",
    "McpServerInfo",
    "create_interop_memory_mcp_server",
]
