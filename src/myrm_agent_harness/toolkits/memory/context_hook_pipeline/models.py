"""Strongly-typed data models for Pluggable Context Hook Pipeline & Memory Injection.

Topic 01 Item 138: PluggableContextHookPipelineAndMemoryInjectionSuite.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContextHookStage(StrEnum):
    """Standardized lifecycle execution points in agent context and reasoning pipeline."""

    BEFORE_AGENT_START = "before_agent_start"  # Environment awareness, persona initialization
    CONTEXT_TRANSFORM = "context_transform"  # Prompt assembly, semantic pruning, memory weaving
    AFTER_TOOL_CALL = "after_tool_call"  # Post-execution reflection, audit trail injection
    BEFORE_LLM_REQUEST = "before_llm_request"  # Final egress sanitization, privacy redaction


class HookExecutionPriority(IntEnum):
    """Execution priority order: lower numbers execute earlier (e.g. 10 runs before 20)."""

    SECURITY_FIRST = 10  # Security gate, compliance redaction
    MEMORY_INJECTION = 20  # Private/Shared memory weaving
    USER_CUSTOM = 30  # Custom persona extensions, specialized prompts
    AUDIT_LOGGING = 40  # Telemetry, observability tracing


class MemoryLayerKind(StrEnum):
    """Categorical boundary for dual-layer memory weaving."""

    PRIVATE_AGENT = "private_agent"  # Scoped exclusively to a specific custom agent persona
    SHARED_GLOBAL = "shared_global"  # Shared across all agents (global policies, user baseline)


class MemoryFragment(BaseModel):
    """Granular memory snippet eligible for dynamic context weaving."""

    model_config = ConfigDict(frozen=True)

    fragment_id: str = Field(description="Unique snippet identifier")
    layer: MemoryLayerKind = Field(description="Ownership tier: private or shared")
    content: str = Field(min_length=1, description="Textual memory fact or instruction")
    weight: float = Field(default=1.0, ge=0.1, le=5.0, description="Priority weight")
    tags: list[str] = Field(default_factory=list, description="Descriptive metadata tags")
    agent_id: str | None = Field(default=None, description="Owner agent ID if private")


class DualLayerMemoryPayload(BaseModel):
    """Input payload bundling private and shared memories for weaving."""

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(description="Target custom agent identifier")
    private_fragments: list[MemoryFragment] = Field(default_factory=list, description="Private memories")
    shared_fragments: list[MemoryFragment] = Field(default_factory=list, description="Shared global memories")
    max_token_budget: int = Field(default=1500, ge=100, le=32000, description="Token budget cap")


class ContextEnvelope(BaseModel):
    """Mutable context state passed through the pluggable hook pipeline."""

    session_id: str = Field(description="Conversation session identifier")
    agent_id: str = Field(description="Agent persona identifier")
    system_prompt: str = Field(description="Current base system prompt")
    injected_memories: list[str] = Field(default_factory=list, description="Appended memory blocks")
    metadata: dict[str, str] = Field(default_factory=dict, description="Arbitrary execution context headers")
    is_blocked: bool = Field(default=False, description="Whether pipeline execution is blocked")
    block_reason: str | None = Field(default=None, description="Reason if blocked by security hook")


class HookExecutionReport(BaseModel):
    """Telemetry report for a single hook invocation."""

    model_config = ConfigDict(frozen=True)

    hook_id: str = Field(description="Identifier of the executing hook")
    stage: ContextHookStage = Field(description="Stage where hook ran")
    priority: int = Field(description="Priority ranking")
    execution_time_ms: float = Field(ge=0.0, description="Wall clock runtime in milliseconds")
    was_modified: bool = Field(description="Whether hook modified context or prompt")
    is_blocked: bool = Field(description="Whether hook blocked execution")
