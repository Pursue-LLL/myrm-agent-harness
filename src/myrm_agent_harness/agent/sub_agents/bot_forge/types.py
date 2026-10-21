"""Types and data structures for Chat-Driven Agent & Team Factory with Safety Envelope.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- PipelineStageEnum
- OverlapVerdictEnum
- ReadinessSeverityEnum
- BuilderAuthority
- BotProfileSpec
- TeamCompositionSpec
- VerificationFinding
- CreationVerificationResult
- RollbackRecord
- PipelineExecutionState

[POS]
Types and data structures for Chat-Driven Agent & Team Factory with Safety Envelope.

"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class PipelineStageEnum(StrEnum):
    """Stages in the deterministic agent creation pipeline."""

    PRECHECK = "precheck"
    NAME_OVERLAP_GUARD = "name_overlap_guard"
    PROFILE_DESIGN = "profile_design"
    PERSONA_MEMORY = "persona_memory"
    ROUTINE_BIND = "routine_bind"
    POST_VERIFICATION = "post_verification"
    ROLLED_BACK = "rolled_back"
    COMPLETED = "completed"


class OverlapVerdictEnum(StrEnum):
    """Verdict of duty or name overlap check against existing registry."""

    UNIQUE = "unique"
    DUPLICATE_NAME = "duplicate_name"
    OVERLAPPING_DUTY = "overlapping_duty"


class ReadinessSeverityEnum(StrEnum):
    """Severity level of readiness dry-run verification."""

    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass
class BuilderAuthority:
    """Authority envelope defining what a creator agent is allowed to build."""

    builder_name: str
    allowed_tools: list[str] = field(default_factory=list)
    allowed_skills: list[str] = field(default_factory=list)
    allowed_mcps: list[str] = field(default_factory=list)
    can_create_agents: bool = True
    max_team_members: int = 6

    def to_dict(self) -> dict[str, object]:
        return {
            "builder_name": self.builder_name,
            "allowed_tools": self.allowed_tools,
            "allowed_skills": self.allowed_skills,
            "allowed_mcps": self.allowed_mcps,
            "can_create_agents": self.can_create_agents,
            "max_team_members": self.max_team_members,
        }


@dataclass
class BotProfileSpec:
    """Specification of an agent profile to be created or cloned."""

    name: str
    display_name: str
    description: str
    system_prompt: str
    model: str = "default-model"
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    cron_routines: list[str] = field(default_factory=list)
    role_type: str = "specialist"  # "lead" | "specialist"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "model": self.model,
            "tools": self.tools,
            "skills": self.skills,
            "mcp_servers": self.mcp_servers,
            "cron_routines": self.cron_routines,
            "role_type": self.role_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BotProfileSpec:
        return cls(
            name=str(data.get("name", "")),
            display_name=str(data.get("display_name", "")),
            description=str(data.get("description", "")),
            system_prompt=str(data.get("system_prompt", "")),
            model=str(data.get("model", "default-model")),
            tools=[str(t) for t in data.get("tools", [])],  # type: ignore[union-attr]
            skills=[str(s) for s in data.get("skills", [])],  # type: ignore[union-attr]
            mcp_servers=[str(m) for m in data.get("mcp_servers", [])],  # type: ignore[union-attr]
            cron_routines=[str(c) for c in data.get("cron_routines", [])],  # type: ignore[union-attr]
            role_type=str(data.get("role_type", "specialist")),
        )


@dataclass
class TeamCompositionSpec:
    """Specification of a Lead + Specialists multi-agent team."""

    team_name: str
    team_purpose: str
    lead: BotProfileSpec
    specialists: list[BotProfileSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "team_name": self.team_name,
            "team_purpose": self.team_purpose,
            "lead": self.lead.to_dict(),
            "specialists": [s.to_dict() for s in self.specialists],
        }


@dataclass
class VerificationFinding:
    """Finding from readiness dry-run verification."""

    code: str
    severity: ReadinessSeverityEnum
    message: str
    next_action: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "next_action": self.next_action,
        }


@dataclass
class CreationVerificationResult:
    """Outcome of pre-check and post-creation verification."""

    passed: bool
    severity: ReadinessSeverityEnum
    findings: list[VerificationFinding] = field(default_factory=list)
    observed_state: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "severity": self.severity.value,
            "findings": [f.to_dict() for f in self.findings],
            "observed_state": self.observed_state,
        }


@dataclass
class RollbackRecord:
    """Audit record capturing an atomic creation rollback."""

    target_name: str
    reason: str
    reverted_agents: list[str] = field(default_factory=list)
    reverted_crons: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "target_name": self.target_name,
            "reason": self.reason,
            "reverted_agents": self.reverted_agents,
            "reverted_crons": self.reverted_crons,
            "timestamp": self.timestamp,
        }


@dataclass
class PipelineExecutionState:
    """Current progression of an agent or team creation pipeline."""

    pipeline_id: str
    target_name: str
    current_stage: PipelineStageEnum
    is_team: bool = False
    created_agents: list[str] = field(default_factory=list)
    verification: CreationVerificationResult | None = None
    rollback: RollbackRecord | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "pipeline_id": self.pipeline_id,
            "target_name": self.target_name,
            "current_stage": self.current_stage.value,
            "is_team": self.is_team,
            "created_agents": self.created_agents,
            "verification": self.verification.to_dict() if self.verification else None,
            "rollback": self.rollback.to_dict() if self.rollback else None,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
