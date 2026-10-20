"""Type definitions for third-party assistant asset detection and ingestion.

Defines schemas for probing competitor data stores and reporting ingestion outcomes
(Hermes, Claude Code, Codex). Whole-instance backup/restore lives in the server's
``instance_archive`` on top of ``infra.state_archive``, not here.
Strict typing applied: No `Any` types allowed.

[INPUT]
- External: pydantic

[OUTPUT]
- CompetitorType: Supported third-party competitor platforms for zero-friction migration.
- CompetitorDetectResult: Result of probing local environment for competitor data stores.
- CompetitorImportResult: Outcome summary after ingesting rules and memories from competitor setups.

[POS]
Type definitions for competitor asset detection and ingestion.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CompetitorType(StrEnum):
    """Supported third-party competitor platforms for zero-friction migration."""

    HERMES = "hermes"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class CompetitorDetectResult(BaseModel):
    """Result of probing local environment for competitor data stores."""

    model_config = ConfigDict(extra="forbid")

    detected_competitors: list[CompetitorType] = Field(
        default_factory=list, description="Competitor software recognized on host"
    )
    hermes_dir: str | None = Field(default=None, description="Discovered path to ~/.hermes if present")
    claude_code_rule_path: str | None = Field(default=None, description="Discovered path to CLAUDE.md if present")
    codex_rule_path: str | None = Field(default=None, description="Discovered path to AGENTS.md if present")


class CompetitorImportResult(BaseModel):
    """Outcome summary after ingesting rules and memories from competitor setups."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="True if import completed without fatal errors")
    imported_rules_count: int = Field(default=0, ge=0, description="Number of agent rules converted")
    imported_skills_count: int = Field(default=0, ge=0, description="Number of custom skills ingested")
    imported_memories_count: int = Field(default=0, ge=0, description="Number of memories/markdown pages created")
    details: list[str] = Field(default_factory=list, description="Detailed ingestion logs or status notices")
