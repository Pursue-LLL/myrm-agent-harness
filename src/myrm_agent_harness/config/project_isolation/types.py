"""Data types and schemas for Untrusted Project Config Isolation and Preflight Diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class ConfigSourceTier(StrEnum):
    """Tier from which the effective configuration was resolved."""

    LOCAL_PROJECT_TRUSTED = "local_project_trusted"
    GLOBAL_USER = "global_user"
    BUILTIN_DEFAULT = "builtin_default"
    LOCAL_PROJECT_UNTRUSTED_REJECTED = "local_project_untrusted_rejected"


class PreflightGateError(Exception):
    """Raised when preflight diagnostic assertions fail or invalid configuration is encountered."""


@dataclass(frozen=True, slots=True)
class MyrmProjectConfigSchema:
    """Strict configuration schema for Myrm project and workspace settings."""

    version: str = "1.0"
    model_tier: str = "standard"
    execution_timeout: float = 30.0
    allow_network: bool = False
    cache_write_read_ratio: float = 1.0
    sandbox_enabled: bool = True
    anti_exfiltration_guard: bool = True
    audit_logging: bool = True
    custom_rules: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, str | float | bool | list[str]]:
        """Serialize configuration to a primitive dictionary."""
        return {
            "version": self.version,
            "model_tier": self.model_tier,
            "execution_timeout": self.execution_timeout,
            "allow_network": self.allow_network,
            "cache_write_read_ratio": self.cache_write_read_ratio,
            "sandbox_enabled": self.sandbox_enabled,
            "anti_exfiltration_guard": self.anti_exfiltration_guard,
            "audit_logging": self.audit_logging,
            "custom_rules": list(self.custom_rules),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class ConfigResolutionContext:
    """Context governing config search order and workspace trust gate."""

    workspace_path: str
    is_project_trusted: bool = False
    global_config_path: str | None = None
    local_config_rel_path: str = ".myrm/config.json"


@dataclass(frozen=True, slots=True)
class DiagnosticCheckResult:
    """Diagnostic outcome of static preflight config verification."""

    is_valid: bool
    version: str
    unknown_keys: tuple[str, ...]
    validation_errors: tuple[str, ...]
    applied_tier: ConfigSourceTier
    effective_config: MyrmProjectConfigSchema
    checked_at: datetime = field(default_factory=_utc_now)
    all_mandatory_features_enabled: bool = True
