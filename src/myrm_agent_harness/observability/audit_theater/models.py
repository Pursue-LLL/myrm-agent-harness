"""
[INPUT]: Raw execution event records, tool execution logs, and resource access payloads.
[OUTPUT]: Strongly typed models for lie-immune in-conversation audit trail and resource-level data access ledgers.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/audit_theater/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ResourceAccessKind(str, Enum):
    """Category of data resource inspected or modified during agent execution."""

    FILE = "file"
    MEMORY = "memory"
    CONNECTOR_MCP = "connector_mcp"
    WEB_NETWORK = "web_network"


class ResourceAccessMode(str, Enum):
    """Operation access mode."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class ResourceAccessEntry(BaseModel):
    """Granular audit record of a specific data resource accessed by tools (lie-immune)."""

    entry_id: str = Field(..., description="Unique entry identifier")
    session_id: str = Field(..., description="Session identifier")
    resource_id: str = Field(..., description="Path, memory key, MCP tool URI, or remote domain")
    kind: ResourceAccessKind = Field(..., description="Resource category")
    mode: ResourceAccessMode = Field(..., description="Access mode (read/write/execute)")
    scope_detail: str = Field(default="", description="Granular scope: e.g. 'lines 1-80', 'collection=workspace'")
    size_bytes: int = Field(default=0, ge=0)
    line_count: int = Field(default=0, ge=0)
    success: bool = Field(default=True)
    timestamp_ms: int = Field(..., description="Authoritative timestamp from backend system clock")


class TimelineAuditEvent(BaseModel):
    """In-conversation chronological audit event representing an action or declared plan."""

    event_id: str = Field(...)
    session_id: str = Field(...)
    step_name: str = Field(..., description="Action step title")
    tool_name: str = Field(..., description="Actual tool or system service called")
    is_plan: bool = Field(default=False, description="True if this is an intention declaration before execution")
    status: str = Field(default="completed", description="'completed' | 'in_progress' | 'failed'")
    duration_ms: int = Field(default=0, ge=0)
    inputs_summary: str = Field(default="", description="Desensitized input summary")
    timestamp_ms: int = Field(...)


class SessionDataAccessLedger(BaseModel):
    """Authoritative data access ledger and audit trail, guaranteed free of model self-narration lies."""

    session_id: str = Field(...)
    resources: List[ResourceAccessEntry] = Field(default_factory=list)
    events: List[TimelineAuditEvent] = Field(default_factory=list)
    total_resources_accessed: int = Field(default=0, ge=0)
    total_files_read: int = Field(default=0, ge=0)
    total_files_written: int = Field(default=0, ge=0)
    total_memories_queried: int = Field(default=0, ge=0)
    total_network_domains_visited: int = Field(default=0, ge=0)
    lie_immune_verified: bool = Field(default=True, description="Always true: sourced 100% from backend event sink")
    digest_sha256: str = Field(..., description="Cryptographic SHA-256 fingerprint over authoritative event sequence")
    generated_at_ms: int = Field(...)
