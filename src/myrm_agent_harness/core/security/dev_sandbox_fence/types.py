"""Data types and schemas for Zero-Production-Write Dev Sandbox and Synthetic Data Fence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class DevExecutionMode(StrEnum):
    """Runtime execution environment tier for agent execution."""

    DEV_ISOLATED = "dev_isolated"
    READONLY_RESEARCH = "readonly_research"
    PRODUCTION_CONTROLLED = "production_controlled"


class ViolationType(StrEnum):
    """Classification of dev sandbox security violations."""

    PROD_DB_WRITE_BLOCKED = "prod_db_write_blocked"
    PROD_BRANCH_PUSH_BLOCKED = "prod_branch_push_blocked"
    SENSITIVE_DIR_WRITE_BLOCKED = "sensitive_dir_write_blocked"
    PROD_CREDENTIAL_SUBSTITUTION = "prod_credential_substitution"


class ZeroProductionWriteViolationError(Exception):
    """Raised when an operation attempts unauthorized production writes in dev mode."""


@dataclass(frozen=True, slots=True)
class SyntheticDataFixture:
    """Approved synthetic or masked read-only dataset fixture."""

    fixture_id: str
    database_type: str
    read_only_uri: str
    sample_count: int = 100
    description: str = ""


@dataclass(frozen=True, slots=True)
class DevSandboxPolicy:
    """Policy rules governing file changes, git branches, and synthetic data in dev mode."""

    allowed_branch_prefixes: tuple[str, ...] = ("agent/dev-", "dev-", "feature/")
    blocked_branches: tuple[str, ...] = ("main", "master", "prod", "production", "release")
    allowed_write_directories: tuple[str, ...] = (
        "src/adapters",
        "tests",
        "mock",
        "sandbox",
        "scratch",
    )
    blocked_sensitive_patterns: tuple[str, ...] = (
        ".github/workflows",
        "deploy/",
        "k8s/",
        "helm/",
        ".env.prod",
        ".env.production",
        "prod_secret",
    )
    enforce_synthetic_data: bool = True


@dataclass(frozen=True, slots=True)
class DevOperationInspection:
    """Operation submitted to dev sandbox fence for policy evaluation."""

    operation_type: str  # "sql", "git_branch", "file_write", "db_connect"
    target: str
    payload: str = ""
    session_id: str = "default_session"


@dataclass(frozen=True, slots=True)
class FenceInspectionResult:
    """Evaluation result from dev sandbox fence."""

    allowed: bool
    violation_type: ViolationType | None
    reason: str
    substituted_target: str | None = None


@dataclass(frozen=True, slots=True)
class DevViolationAlert:
    """Audit log entry for dev sandbox security boundary breaches."""

    alert_id: str
    session_id: str
    operation_type: str
    violation_type: ViolationType
    reason: str
    target: str
    timestamp: datetime = field(default_factory=_utc_now)
