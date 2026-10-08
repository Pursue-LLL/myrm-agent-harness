"""Server factory creating standard MCP server with ai-memory wire parity.

Exposes standard MCP tools allowing external IDEs (Claude Code, Cursor, Codex)
to interact seamlessly with Myrm's underlying memory and handoff infrastructure.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.handoff::AgentHandoffEngine (POS: Public interface for agent handoff management
  and session finalization.)
- toolkits.memory.agent_surface.mcp.ai_memory_wire_adapter::AiMemoryWireAdapter (POS: Wire-format adapter
  emulating the 5.3k Star ai-memory MCP tool protocol.)
- toolkits.memory.agent_surface.mcp.types::McpServerInfo (POS: Data models for ai-memory wire format
  interoperability and cross-tool MCP gateway.)
- toolkits.memory.privacy_gate::MemoryPrivacyBoundaryGate (POS: Public entry point for memory privacy
  boundary and allowlist gate.)
- External: mcp

[OUTPUT]
- create_interop_memory_mcp_server: Create and configure an MCP server with full ai-memory wire protocol
  parity.

[POS]
Server factory creating standard MCP server with ai-memory wire parity.
"""

from __future__ import annotations

import logging

from mcp.server.mcpserver import MCPServer

from myrm_agent_harness.toolkits.memory.agent_surface.mcp.ai_memory_wire_adapter import (
    AiMemoryWireAdapter,
)
from myrm_agent_harness.toolkits.memory.agent_surface.mcp.types import McpServerInfo
from myrm_agent_harness.toolkits.memory.handoff import AgentHandoffEngine
from myrm_agent_harness.toolkits.memory.privacy_gate import MemoryPrivacyBoundaryGate

logger = logging.getLogger(__name__)


def create_interop_memory_mcp_server(
    handoff_engine: AgentHandoffEngine | None = None,
    privacy_gate: MemoryPrivacyBoundaryGate | None = None,
    server_name: str = "myrm-memory-mcp",
) -> tuple[MCPServer, McpServerInfo]:
    """Create and configure an MCP server with full ai-memory wire protocol parity.

    Args:
        handoff_engine: Optional injected AgentHandoffEngine instance.
        privacy_gate: Optional injected MemoryPrivacyBoundaryGate instance.
        server_name: Name identifier for the MCP server.

    Returns:
        Tuple of (configured MCPServer, McpServerInfo descriptor).
    """
    adapter = AiMemoryWireAdapter(
        handoff_engine=handoff_engine,
        privacy_gate=privacy_gate,
    )
    server = MCPServer(name=server_name)

    @server.tool(
        name="query_memory",
        description="Search past memories, architectural decisions, and project facts (ai-memory compatible).",
    )
    def query_memory_tool(query: str, limit: int = 5) -> str:
        return adapter.query_memory(query=query, limit=limit)

    @server.tool(
        name="get_handoff",
        description="Retrieve active handoff memorandum with goals, next actions, and pitfalls (ai-memory compatible).",
    )
    def get_handoff_tool(target_profile_id: str = "") -> str:
        prof = target_profile_id.strip() if target_profile_id.strip() else None
        return adapter.get_handoff(target_profile_id=prof)

    @server.tool(
        name="finalize_session",
        description="Finalize working session and write durable handoff memorandum to Myrm storage (ai-memory compatible).",
    )
    def finalize_session_tool(
        summary: str,
        next_steps: list[str],
        failed_approaches: list[str] | None = None,
    ) -> str:
        return adapter.finalize_session(
            summary=summary,
            next_steps=next_steps,
            failed_approaches=failed_approaches or [],
        )

    @server.tool(
        name="remember",
        description="Save an architectural fact, rule, or constraint under privacy gate review (ai-memory compatible).",
    )
    def remember_tool(topic: str, note: str, source_file: str = "") -> str:
        src = source_file.strip() if source_file.strip() else None
        return adapter.remember(topic=topic, note=note, source_file=src)

    registered_tools = ["query_memory", "get_handoff", "finalize_session", "remember"]
    info = McpServerInfo(
        server_name=server_name,
        version="1.0.0",
        compatible_with=["ai-memory-v1", "claude-code", "cursor-ide", "codex"],
        tools_exposed=registered_tools,
    )

    logger.info("Created interop memory MCP server '%s' exposing tools: %s", server_name, registered_tools)
    return server, info
