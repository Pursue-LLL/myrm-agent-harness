# [POS]: myrm_agent_harness/toolkits/memory/agent_surface/mcp/types.py
# [INPUT]: pydantic
# [OUTPUT]: AiMemoryQueryRequest, AiMemoryQueryResult, AiMemoryFinalizeRequest, AiMemoryFinalizeResult, AiMemoryRememberRequest, AiMemoryRememberResult, McpServerInfo
"""Data models for ai-memory wire format interoperability and cross-tool MCP gateway.

Defines schemas mirroring the 5.3k Star ai-memory MCP tool signatures
(query_memory, get_handoff, finalize_session, remember) to enable zero-friction
drop-in replacement for external agents (Claude Code, Cursor, Codex).
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict, Field


class AiMemoryQueryRequest(BaseModel):
    """Query request matching ai-memory query_memory tool signature."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Keywords or questions to search across memory")
    limit: int = Field(default=5, ge=1, le=50, description="Maximum retrieved memory items")


class AiMemoryQueryResult(BaseModel):
    """Formatted markdown search result mirroring ai-memory wire output."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., description="Query string executed")
    content_markdown: str = Field(..., description="Formatted markdown string of matching memories")
    count: int = Field(ge=0, description="Total number of results returned")


class AiMemoryFinalizeRequest(BaseModel):
    """Request matching ai-memory finalize-session tool signature."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        default_factory=lambda: f"mcp-session-{int(time.time())}",
        description="Session identifier being finalized",
    )
    source_profile_id: str = Field(default="external-ide-agent", description="Calling agent profile ID")
    summary: str = Field(..., min_length=1, description="Summary of working goal and progress achieved")
    next_steps: list[str] = Field(default_factory=list, description="Immediate next action items for successor")
    failed_approaches: list[str] = Field(
        default_factory=list, description="Approaches attempted and discarded with reasons"
    )


class AiMemoryFinalizeResult(BaseModel):
    """Confirmation output mirroring ai-memory finalize response."""

    model_config = ConfigDict(extra="forbid")

    handoff_id: str = Field(..., description="Durable handoff memorandum ID")
    status: str = Field(..., description="Status of the handoff record")
    persisted_path: str = Field(..., description="On-disk storage path of the memorandum")
    summary_markdown: str = Field(..., description="Human-readable markdown summary")


class AiMemoryRememberRequest(BaseModel):
    """Request matching ai-memory remember/save_fact tool signature."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=1, description="Domain topic, entity name, or rule category")
    note: str = Field(..., min_length=1, description="Fact, rule, or architectural constraint content")
    source_file: str | None = Field(default=None, description="Optional source file or reference origin")


class AiMemoryRememberResult(BaseModel):
    """Result confirming durable memory ingestion under privacy gate review."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(..., description="Deterministic or generated fact identifier")
    topic: str = Field(..., description="Memory topic/entity")
    status: str = Field(..., description="Status: stored, sanitized_and_stored, or rejected")
    was_redacted: bool = Field(..., description="True if privacy gate scrubbed secrets before saving")


class McpServerInfo(BaseModel):
    """Metadata describing the active interoperability memory MCP server."""

    model_config = ConfigDict(extra="forbid")

    server_name: str = Field(default="myrm-memory-mcp", description="Name of the MCP server")
    version: str = Field(default="1.0.0", description="Semantic version of server")
    compatible_with: list[str] = Field(
        default_factory=lambda: ["ai-memory-v1", "claude-code", "cursor-ide"],
        description="List of compatible tool and client protocols",
    )
    tools_exposed: list[str] = Field(
        default_factory=list, description="List of registered MCP tool names"
    )
