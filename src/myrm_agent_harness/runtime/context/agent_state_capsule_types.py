"""Data contracts and models for Universal Agent State Capsule.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CapsuleMergeStrategy: Conflict resolution strategy when migrating an agent capsule.
- CapsuleIntegrityError: Raised when an agent state capsule payload fails integrity verification.
- CapsuleHeader: Metadata and tamper-evidence checksum header of the state capsule.
- AgentProfileCapsule: Portable identity and model configuration specification.
- SkillCapsuleEntry: Custom skill and external tool declaration bundled with the agent.
- MemoryCapsuleEntry: Episodic, semantic, procedural or working memory unit.
- SessionCheckpointCapsuleEntry: Structured epoch summary and milestone checkpoint.
- UniversalAgentCapsule: Fully articulated, portable state capsule payload.
- CapsuleEnvironmentDiagnostic: Pre-flight diagnostic report for target runtime readiness.
- ResolvedMigrationBundle: Output state bundle resolved according to the selected merge strategy.

[POS]
Data contracts and models for Universal Agent State Capsule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapsuleMergeStrategy(StrEnum):
    """Conflict resolution strategy when migrating an agent capsule."""

    CREATE_NEW = "create_new"
    OVERWRITE = "overwrite"
    INCREMENTAL_MERGE = "incremental_merge"


class CapsuleIntegrityError(Exception):
    """Raised when an agent state capsule payload fails integrity verification."""


@dataclass(frozen=True)
class CapsuleHeader:
    """Metadata and tamper-evidence checksum header of the state capsule."""

    schema_version: str
    capsule_id: str
    created_at_utc: str
    source_host: str
    checksum_sha256: str
    encryption_algo: str = "NONE"


@dataclass(frozen=True)
class AgentProfileCapsule:
    """Portable identity and model configuration specification."""

    agent_id: str
    name: str
    description: str
    system_prompt: str
    model_provider: str
    model_name: str
    temperature: float
    max_tokens: int
    metadata: dict[str, str]


@dataclass(frozen=True)
class SkillCapsuleEntry:
    """Custom skill and external tool declaration bundled with the agent."""

    skill_id: str
    name: str
    description: str
    code_or_config: str
    mcp_server_ref: str
    enabled: bool = True


@dataclass(frozen=True)
class MemoryCapsuleEntry:
    """Episodic, semantic, procedural or working memory unit."""

    memory_id: str
    memory_type: str
    content: str
    importance: float
    tags: tuple[str, ...]
    created_at_utc: str
    embedding_vector: tuple[float, ...] | None = None


@dataclass(frozen=True)
class SessionCheckpointCapsuleEntry:
    """Structured epoch summary and milestone checkpoint."""

    session_id: str
    epoch_index: int
    summary_text: str
    created_at_utc: str


@dataclass(frozen=True)
class UniversalAgentCapsule:
    """Fully articulated, portable state capsule payload."""

    header: CapsuleHeader
    profile: AgentProfileCapsule
    skills: tuple[SkillCapsuleEntry, ...]
    memories: tuple[MemoryCapsuleEntry, ...]
    checkpoints: tuple[SessionCheckpointCapsuleEntry, ...]


@dataclass(frozen=True)
class CapsuleEnvironmentDiagnostic:
    """Pre-flight diagnostic report for target runtime readiness."""

    missing_env_vars: tuple[str, ...]
    missing_tools: tuple[str, ...]
    warnings: tuple[str, ...]
    is_ready: bool


@dataclass(frozen=True)
class ResolvedMigrationBundle:
    """Output state bundle resolved according to the selected merge strategy."""

    profile: AgentProfileCapsule
    skills: tuple[SkillCapsuleEntry, ...]
    memories: tuple[MemoryCapsuleEntry, ...]
    checkpoints: tuple[SessionCheckpointCapsuleEntry, ...]
    strategy_applied: CapsuleMergeStrategy
    actions_taken: tuple[str, ...]
