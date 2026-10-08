"""Types and schemas for inherited identity protection and session resumption."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AgentSessionRefKind(StrEnum):
    """Kind of agent session reference."""

    ID = "id"
    PATH = "path"


class AgentSessionRef(BaseModel):
    """Reference to an agent session."""

    kind: AgentSessionRefKind
    value: str


class PersistedAgentSession(BaseModel):
    """Persisted session descriptor for an official agent."""

    source: str
    agent: str
    session_ref: AgentSessionRef


class AgentResumePlan(BaseModel):
    """Resolved execution plan for resuming an agent session."""

    agent: str
    argv: list[str]
    dedupe_key: str


class SanitizationPolicy(BaseModel):
    """Policy governing terminal environment variable sanitization."""

    model_config = ConfigDict(frozen=True)

    denied_env_keys: frozenset[str] = Field(default_factory=frozenset)
    allow_system_only: bool = False
    extra_denied_prefixes: tuple[str, ...] = Field(default_factory=tuple)


class SanitizationResult(BaseModel):
    """Result of stripping inherited terminal and session identity."""

    sanitized_env: dict[str, str] = Field(default_factory=dict)
    purged_keys: list[str] = Field(default_factory=list)
    purged_count: int = 0
    is_isolated: bool = True
