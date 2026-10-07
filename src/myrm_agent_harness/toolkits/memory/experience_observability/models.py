# [POS]: myrm_agent_harness.toolkits.memory.experience_observability.models
# [INPUT]: None (Standard library and Pydantic)
# [OUTPUT]: HostAccessChannel, LifecycleEventKind, ExperienceEffectStatus, LifecycleEventPayload, SessionTraceEvidence, ExperienceObservabilityMetric, HostPluginConfig

"""Domain models for zero-refactor host lifecycle plugin and experience observability.

P1 delivery for Item 108 in topic_01 memory roadmap.
Supports Plugin/MCP/Skill three-way integration and triad observability dashboard.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class HostAccessChannel(StrEnum):
    """Integration access channel for memory experience system."""

    PLUGIN = "plugin"
    MCP = "mcp"
    SKILL = "skill"


class LifecycleEventKind(StrEnum):
    """Host lifecycle event kind intercepted by zero-refactor plugin."""

    SESSION_START = "session_start"
    USER_MESSAGE = "user_message"
    TOOL_CALL = "tool_call"
    TASK_COMPLETED = "task_completed"


class ExperienceEffectStatus(StrEnum):
    """Evaluation status for observed injected experience impact."""

    EFFECTIVE = "effective"
    NEUTRAL = "neutral"
    ADVERSE = "adverse"


class LifecycleEventPayload(BaseModel):
    """Event data captured through host lifecycle hooks."""

    event_kind: LifecycleEventKind = Field(description="Host lifecycle event type")
    session_id: str = Field(description="Host conversation or session identifier")
    user_prompt: str = Field(default="", description="User input text if applicable")
    tool_name: str = Field(default="", description="Tool invocation name if applicable")
    status: str = Field(default="ok", description="Execution status or outcome")
    metadata: dict[str, str] = Field(default_factory=dict, description="Custom metadata tags")


class SessionTraceEvidence(BaseModel):
    """Traceable evidence linking an experience item to its originating session."""

    session_id: str = Field(description="Unique source session identifier")
    title: str = Field(description="Descriptive title of the source session")
    trajectory_summary: str = Field(description="Summary of the key actions and breakthroughs")
    key_evidence_snippets: list[str] = Field(default_factory=list, description="Raw quote or evidence snippets")
    agent_role: str = Field(default="GeneralAssistant", description="Agent role in originating trajectory")
    timestamp: str = Field(description="ISO 8601 creation timestamp")


class ExperienceObservabilityMetric(BaseModel):
    """Observability telemetry metric for a procedure experience item."""

    entry_id: str = Field(description="Target procedure experience entry identifier")
    name: str = Field(description="Human readable experience name")
    source_session_id: str = Field(description="Originating session identifier for traceability")
    access_channel: HostAccessChannel = Field(
        default=HostAccessChannel.PLUGIN,
        description="Primary access channel (plugin/mcp/skill)",
    )
    recall_count: int = Field(default=0, description="Cumulative count of recall hits")
    injection_count: int = Field(default=0, description="Cumulative count of prompt/hook injections")
    success_count: int = Field(default=0, description="Tasks completed successfully following injection")
    dispute_count: int = Field(default=0, description="Times the agent corrected or rejected the experience")
    success_rate: float = Field(default=1.0, description="Success ratio between 0.0 and 1.0")
    effect_status: ExperienceEffectStatus = Field(
        default=ExperienceEffectStatus.EFFECTIVE,
        description="Categorical impact status (effective/neutral/adverse)",
    )
    last_observed_at: str | None = Field(default=None, description="ISO timestamp of last event")


class HostPluginConfig(BaseModel):
    """Configuration for zero-refactor host lifecycle plugin."""

    enabled: bool = Field(default=True, description="Whether lifecycle hooks are active")
    active_channel: HostAccessChannel = Field(
        default=HostAccessChannel.PLUGIN,
        description="Selected integration channel",
    )
    auto_warmup: bool = Field(default=True, description="Warm up experience recall on session start")
    auto_capture: bool = Field(default=True, description="Non-invasively capture tool & message context")
    auto_commit: bool = Field(default=True, description="Trigger two-phase commit on task completion")
    monitored_host: str = Field(default="generic_agent_host", description="Target host name (e.g. claude_code, cursor, hermes)")
