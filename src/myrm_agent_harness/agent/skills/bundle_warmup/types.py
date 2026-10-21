"""Domain types and contracts for Skill Bundles Batch Manifest & Lifecycle Warmup Manager (Item 41).

[INPUT]
- Manifest specifications, bundle skill requirements, warmup probe criteria,
  and session-scoped activation parameters.

[OUTPUT]
- Strongly-typed models for SkillBundleManifest, BundleSkillSpec, WarmupStatus,
  BundleWarmupReport, and BundleActivationRecord.

[POS]
- Harness skills domain models for scenario-based bundle packaging and runtime warmup.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class WarmupStatus(enum.StrEnum):
    """Runtime lifecycle pre-flight warmup and readiness status."""

    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"


class BundleCategory(enum.StrEnum):
    """Business vertical category of the skill bundle."""

    CODING = "coding"
    WRITING = "writing"
    MARKETING = "marketing"
    FINANCE = "finance"
    SECURITY = "security"
    CUSTOM = "custom"


@dataclass(frozen=True)
class BundleSkillSpec:
    """Individual skill definition within a packaged bundle manifest."""

    skill_id: str
    name: str
    description: str
    required_env_vars: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    is_optional: bool = False


@dataclass(frozen=True)
class BundleWarmupCheck:
    """Diagnostic check item evaluated during bundle pre-flight warmup."""

    check_name: str
    status: WarmupStatus
    message: str
    is_resolved: bool = True


@dataclass(frozen=True)
class BundleWarmupReport:
    """Consolidated readiness report produced after probe warmup."""

    bundle_id: str
    overall_status: WarmupStatus
    checks: list[BundleWarmupCheck] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class SkillBundleManifest:
    """Standardized batch manifest packaging scenario-tailored skills."""

    bundle_id: str
    name: str
    description: str
    category: BundleCategory
    skills: list[BundleSkillSpec] = field(default_factory=list)
    author: str = "system"
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class BundleActivationRecord:
    """Record of an activated skill bundle mounted into a session or agent profile."""

    session_id: str
    bundle_id: str
    activated_skills: list[str] = field(default_factory=list)
    warmup_status: WarmupStatus = WarmupStatus.READY
    activated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
