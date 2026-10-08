"""Data contracts and type definitions for cold start context profiling and on-demand MCP mounting.

Provides strong-typed abstractions for breaking down baseline prefill tokens across system prompt,
built-in tools, MCP servers, and long-term memory, enabling dynamic session-level hibernation.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ContextComponentKind: Categorization of initial baseline context payload components.
- McpServerMountState: Lifecycle mounting state of an MCP server within the session.
- ContextComponentProfile: Token consumption footprint of an individual context component.
- McpServerDescriptor: Specification of an external MCP server and its tool schemas.
- ColdStartContextProfile: Comprehensive breakdown of cold-start prefill tokens before user dialogue.
- McpMountMutationResult: Outcome of hibernating or re-activating an MCP server.

[POS]
Data contracts and type definitions for cold start context profiling and on-demand MCP mounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ContextComponentKind(str, Enum):
    """Categorization of initial baseline context payload components."""

    SYSTEM_PROMPT = "system_prompt"
    CORE_TOOLS = "core_tools"
    MCP_EXTERNAL_TOOLS = "mcp_external_tools"
    INSTRUCTION_MEMORY = "instruction_memory"
    USER_HISTORY = "user_history"


class McpServerMountState(str, Enum):
    """Lifecycle mounting state of an MCP server within the session."""

    MOUNTED_ACTIVE = "mounted_active"
    SLEEPING = "sleeping"
    ON_DEMAND_STANDBY = "on_demand_standby"


@dataclass(frozen=True)
class ContextComponentProfile:
    """Token consumption footprint of an individual context component."""

    kind: ContextComponentKind
    name: str
    character_count: int
    estimated_tokens: int
    percentage: float
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class McpServerDescriptor:
    """Specification of an external MCP server and its tool schemas."""

    server_id: str
    display_name: str
    tool_names: list[str]
    estimated_schema_tokens: int
    mount_state: McpServerMountState = McpServerMountState.MOUNTED_ACTIVE
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ColdStartContextProfile:
    """Comprehensive breakdown of cold-start prefill tokens before user dialogue."""

    session_id: str
    total_estimated_tokens: int
    components: list[ContextComponentProfile]
    mounted_mcp_servers: list[McpServerDescriptor]
    warnings: list[str] = field(default_factory=list)
    suggested_mcp_sleep: list[str] = field(default_factory=list)

    @property
    def mcp_tokens_ratio(self) -> float:
        """Proportion of total tokens consumed by external MCP tool schemas."""
        if self.total_estimated_tokens <= 0:
            return 0.0
        mcp_tokens = sum(
            c.estimated_tokens
            for c in self.components
            if c.kind == ContextComponentKind.MCP_EXTERNAL_TOOLS
        )
        return mcp_tokens / self.total_estimated_tokens


@dataclass(frozen=True)
class McpMountMutationResult:
    """Outcome of hibernating or re-activating an MCP server."""

    server_id: str
    old_state: McpServerMountState
    new_state: McpServerMountState
    tokens_delta: int
    message: str
