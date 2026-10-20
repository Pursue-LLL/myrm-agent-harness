"""Type definitions for Heterogeneous External Agent Adapter and Subagent Bundle Manager.

[INPUT]
- __future__
- enum
- pydantic

[OUTPUT]
- ExternalAgentTypeEnum
- BundleExecutionModeEnum
- SubagentInstanceStatusEnum
- ExternalBundleProfileSpec
- SubagentInstanceRecord
- BatchDispatchTask
- BatchDispatchResult

[POS]
Type definitions for Heterogeneous External Agent Adapter and Subagent Bundle Manager.

"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ExternalAgentTypeEnum(StrEnum):
    """Supported external agent types."""

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    GEMINI_CLI = "gemini_cli"
    CUSTOM = "custom"


class BundleExecutionModeEnum(StrEnum):
    """Execution sandbox mode for external subagents."""

    NATIVE_CLI = "native_cli"
    DOCKER_CONTAINER = "docker_container"
    SANDBOX_ISOLATED = "sandbox_isolated"


class SubagentInstanceStatusEnum(StrEnum):
    """Lifecycle status of an external subagent instance."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class ExternalBundleProfileSpec(BaseModel):
    """Packaging specification for a third-party CLI agent (DeepSeek RC.8 Bundle)."""

    bundle_id: str = Field(..., description="Unique bundle identifier (e.g. subagent-codex)")
    agent_type: ExternalAgentTypeEnum = Field(..., description="Target agent family")
    display_name: str = Field(..., description="Human-friendly label")
    description: str = Field(..., description="Specialty description of the external agent")
    binary_name: str = Field(..., description="CLI executable command name (e.g. codex, claude)")
    command_template: str = Field(default="{binary} --print --prompt '{prompt}'", description="Execution template")
    capabilities: list[str] = Field(default_factory=list, description="Claimed capabilities (code, test, review)")
    env_whitelist: list[str] = Field(default_factory=list, description="Whitelisted environment variable names")
    allowed_roots: list[str] = Field(default_factory=list, description="Permitted directory path scopes")
    execution_mode: BundleExecutionModeEnum = Field(default=BundleExecutionModeEnum.SANDBOX_ISOLATED)
    max_concurrency: int = Field(default=5, ge=1, le=20, description="Max parallel instances for this bundle")
    is_installed: bool = Field(default=False, description="Whether executable was detected on host path")
    version: str = Field(default="1.0.0", description="Reported or detected version")


class SubagentInstanceRecord(BaseModel):
    """State record of an instantiated external subagent worker."""

    instance_id: str = Field(..., description="Unique instance ID (e.g. inst-codex-frontend-8f12)")
    bundle_id: str = Field(..., description="Bundle specification used")
    session_id: str = Field(..., description="Parent chat/session ID")
    role_label: str = Field(..., description="Task role label (e.g. frontend-coder, auditor)")
    status: SubagentInstanceStatusEnum = Field(default=SubagentInstanceStatusEnum.PENDING)
    pid: int = Field(default=0, description="OS process ID if running")
    task_prompt: str = Field(..., description="Dispatched prompt or instruction")
    target_workdir: str = Field(..., description="Effective working directory for this instance")
    created_at: float
    started_at: float | None = None
    completed_at: float | None = None
    exit_code: int | None = None
    stdout_chunks: list[str] = Field(default_factory=list, description="Aggregated stdout stream lines")
    artifacts: list[dict[str, str]] = Field(default_factory=list, description="Materialized artifacts/diffs")
    error: str | None = None


class BatchDispatchTask(BaseModel):
    """Single subagent task specification in a batch dispatch request."""

    bundle_id: str = Field(..., description="Bundle ID to instantiate (e.g. subagent-codex)")
    role_label: str = Field(..., description="Role label for this subagent instance")
    task_prompt: str = Field(..., description="Specific goal or instruction")
    target_subdir: str = Field(default="", description="Optional workspace subdirectory scope")
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0, description="Execution timeout limit")


class BatchDispatchResult(BaseModel):
    """Response returned upon batch multiplexed dispatch."""

    batch_id: str = Field(..., description="Unique batch dispatch ID")
    session_id: str = Field(..., description="Target session ID")
    total_dispatched: int = Field(..., description="Number of instances concurrently launched")
    dispatched_instances: list[SubagentInstanceRecord] = Field(default_factory=list)
