# [POS]: myrm_agent_harness/toolkits/memory/agent_surface/mcp/__init__.py
# [INPUT]: None
# [OUTPUT]: AiMemoryWireAdapter, create_interop_memory_mcp_server, types
"""Public entry point for ai-memory wire interoperability and MCP server gateway.

Exposes drop-in wire-compatible tools and MCP server factory for external agents
(Claude Code, Cursor, Codex).
Strict typing applied: No `Any` types allowed.
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
