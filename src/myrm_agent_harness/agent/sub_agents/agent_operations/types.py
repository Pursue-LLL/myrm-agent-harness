"""[INPUT] Pydantic models for Agent-Owned multi-agent execution context.
[OUTPUT] Strong types: AgentProviderConfig, AgentScopedError, AgentRosterEntry, AgentOwnedExecutionContext.
[POS] Core data models for Agent-Owned operations isolation.
"""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field


class AgentProviderConfig(BaseModel):
    """Provider configuration owned exclusively by a specific agent instance."""

    provider_name: str = Field(..., description="Provider backend identifier (e.g. openai, anthropic, deepseek)")
    model_name: str = Field(..., description="Target model identifier (e.g. deepseek-chat, claude-3-5-sonnet)")
    api_base: str | None = Field(default=None, description="Optional custom base URL for private API or proxy")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int | None = Field(default=None, description="Maximum token generation limit")
    timeout_seconds: float = Field(default=60.0, gt=0.0, description="Per-request invocation timeout in seconds")


class AgentScopedError(BaseModel):
    """Operation-specific error isolated to the originating agent instance."""

    error_id: str = Field(default_factory=lambda: f"err_{uuid.uuid4().hex[:10]}")
    agent_id: str = Field(..., description="Identifier of the agent where the error occurred")
    operation: str = Field(..., description="Operation being executed when failure happened")
    error_type: str = Field(..., description="Categorized error class name")
    message: str = Field(..., description="Sanitized diagnostic error message")
    timestamp: float = Field(default_factory=time.time, description="Epoch timestamp of error occurrence")
    fatal: bool = Field(default=False, description="Whether the error halted the agent execution")
    context: dict[str, str] = Field(default_factory=dict, description="Key-value operational metadata without leaking global session state")


class AgentRosterEntry(BaseModel):
    """Standardized list-form roster representation of a registered agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    role: str = Field(..., description="Functional role of the agent")
    parent_agent_id: str | None = Field(default=None, description="Immediate supervisor/orchestrator ID if delegated")
    session_id: str = Field(default="", description="Chat session identifier")
    provider_model: str = Field(..., description="Model string owned by the agent")
    capabilities: list[str] = Field(default_factory=list, description="Declared capability tags")
    allowlist: list[str] = Field(default_factory=list, description="Allowed tool or action identifiers")
    error_count: int = Field(default=0, description="Number of isolated errors in the agent's stack")
    is_healthy: bool = Field(default=True, description="Whether the agent is currently free of fatal errors")


class AgentOwnedExecutionContext(BaseModel):
    """Full-lifecycle execution context owned strictly by an agent instance."""

    agent_id: str = Field(..., description="Unique identifier for the agent instance")
    role: str = Field(default="general_worker", description="Functional role description")
    session_id: str = Field(default="", description="Parent chat session identifier")
    parent_agent_id: str | None = Field(default=None, description="Parent agent identifier")
    provider_config: AgentProviderConfig = Field(..., description="Agent-owned provider setup")
    capabilities: list[str] = Field(default_factory=list, description="Agent declared capability targets")
    allowlist: list[str] = Field(default_factory=list, description="Agent-scoped allowed tools or capability actions")
    error_stack: list[AgentScopedError] = Field(default_factory=list, description="Isolated error stack owned by this agent")

    def resolve_capability(self, target_capability: str) -> bool:
        """Check whether a target capability is permitted under the agent's own allowlist and declared capabilities."""
        if not self.allowlist:
            # If allowlist is empty, fallback to checking declared capabilities
            return target_capability in self.capabilities
        # Check explicit allowlist or wildcard
        return "*" in self.allowlist or target_capability in self.allowlist

    def record_error(
        self,
        operation: str,
        error_type: str,
        message: str,
        fatal: bool = False,
        context: dict[str, str] | None = None,
    ) -> AgentScopedError:
        """Record an operation failure strictly within the agent-owned stack without leaking to parent."""
        scoped_err = AgentScopedError(
            agent_id=self.agent_id,
            operation=operation,
            error_type=error_type,
            message=message,
            fatal=fatal,
            context=context or {},
        )
        self.error_stack.append(scoped_err)
        return scoped_err

    def clear_errors(self) -> None:
        """Clear the isolated error stack."""
        self.error_stack.clear()

    def to_roster_entry(self) -> AgentRosterEntry:
        """Export entry for the standardized list-form agent roster."""
        has_fatal = any(err.fatal for err in self.error_stack)
        return AgentRosterEntry(
            agent_id=self.agent_id,
            role=self.role,
            parent_agent_id=self.parent_agent_id,
            session_id=self.session_id,
            provider_model=f"{self.provider_config.provider_name}/{self.provider_config.model_name}",
            capabilities=list(self.capabilities),
            allowlist=list(self.allowlist),
            error_count=len(self.error_stack),
            is_healthy=not has_fatal,
        )
