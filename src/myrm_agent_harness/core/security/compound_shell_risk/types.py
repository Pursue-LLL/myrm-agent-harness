"""Data structures and types for Compound Shell Risk Interceptor and Edge Auxiliary Suite."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class CommandRiskLevel(StrEnum):
    """Risk severity categorization."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FirewallVerdict(StrEnum):
    """Enforcement outcome of the compound command firewall."""

    ALLOW = "allow"
    AUDIT_REQUIRED = "audit_required"
    BLOCK = "block"


class AuxiliaryTaskType(StrEnum):
    """Category of low-latency edge auxiliary tasks."""

    COMMAND_SCREENING = "command_screening"
    TITLE_GENERATION = "title_generation"
    PROFILE_COMPACTION = "profile_compaction"


@dataclass(frozen=True)
class CompoundCheckResult:
    """Outcome of compound shell command inspection."""

    raw_command: str
    is_compound: bool
    operators_found: list[str]
    sub_commands: list[str]
    verdict: FirewallVerdict
    risk_level: CommandRiskLevel
    reason: str | None = None


@dataclass(frozen=True)
class CommandScreeningResult:
    """Outcome of edge model command pre-screening."""

    command: str
    risk_level: CommandRiskLevel
    is_dangerous: bool
    risk_factors: list[str]
    execution_time_ms: float
    summary: str


@dataclass(frozen=True)
class TitleGenerationResult:
    """Outcome of edge model session title generation."""

    title: str
    suggested_tags: list[str]
    execution_time_ms: float


@dataclass(frozen=True)
class ProfileCompactionResult:
    """Outcome of edge model user profile compaction."""

    compacted_profile: Mapping[str, str]
    extracted_preferences: list[str]
    execution_time_ms: float
