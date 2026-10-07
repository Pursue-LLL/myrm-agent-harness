"""Type definitions and contracts for memory privacy boundary and allowlist gate.

Defines sensitivity classifications, violation taxonomies, detection findings,
and configuration constraints.
Strict typing applied: No `Any` types allowed.

[INPUT]
- External: pydantic

[OUTPUT]
- PrivacySensitivityLevel: Graded sensitivity level of memory contents.
- PrivacyViolationType: Taxonomy of detected sensitive data violations.
- SecretFinding: Atomic finding of a sensitive secret or prohibited pattern.
- PrivacyCheckResult: Comprehensive evaluation result from privacy boundary gate inspection.
- MemoryPrivacyConfig: Configuration options for memory privacy boundary gate.
- MemoryPrivacyError: Base exception for memory privacy violations.
- PrivacyBoundaryViolationError: Raised when critical secrets or prohibited paths violate boundary policies.
- InvalidPrivacyConfigError: Raised when memory privacy configuration parameters are invalid.

[POS]
Type definitions and contracts for memory privacy boundary and allowlist gate.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrivacySensitivityLevel(StrEnum):
    """Graded sensitivity level of memory contents."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    CRITICAL_SECRET = "critical_secret"


class PrivacyViolationType(StrEnum):
    """Taxonomy of detected sensitive data violations."""

    API_KEY = "api_key"
    PRIVATE_KEY = "private_key"
    CONNECTION_URI = "connection_uri"
    PASSWORD_FIELD = "password_field"
    JWT_TOKEN = "jwt_token"
    EXCLUDED_PATH = "excluded_path"
    CUSTOM_RULE = "custom_rule"


class SecretFinding(BaseModel):
    """Atomic finding of a sensitive secret or prohibited pattern."""

    model_config = ConfigDict(extra="forbid")

    violation_type: PrivacyViolationType = Field(..., description="Classification of the violation")
    snippet_masked: str = Field(..., description="Masked evidence snippet for auditing without leaking")
    category: str = Field(..., description="General category name")
    line_number: int = Field(default=1, ge=1, description="Line number where secret was detected")


class PrivacyCheckResult(BaseModel):
    """Comprehensive evaluation result from privacy boundary gate inspection."""

    model_config = ConfigDict(extra="forbid")

    passed: bool = Field(..., description="True if content complies with privacy policies")
    sensitivity_level: PrivacySensitivityLevel = Field(..., description="Assessed overall sensitivity level")
    findings: list[SecretFinding] = Field(default_factory=list, description="Collection of detected findings")
    redacted_content: str = Field(..., description="Content with detected secrets replaced by safe masks")
    violation_reason: str | None = Field(default=None, description="Detailed explanation if rejected")


class MemoryPrivacyConfig(BaseModel):
    """Configuration options for memory privacy boundary gate."""

    model_config = ConfigDict(extra="forbid")

    allow_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns or keywords explicitly permitted to bypass filtering",
    )
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns or regexes that mandate absolute rejection",
    )
    block_on_critical: bool = Field(
        default=True,
        description="Whether detecting critical secrets immediately triggers hard veto",
    )
    strict_mode: bool = Field(
        default=False,
        description="If True, any non-public finding vetoes persistence regardless of masking",
    )


class MemoryPrivacyError(Exception):
    """Base exception for memory privacy violations."""


class PrivacyBoundaryViolationError(MemoryPrivacyError):
    """Raised when critical secrets or prohibited paths violate boundary policies."""


class InvalidPrivacyConfigError(MemoryPrivacyError):
    """Raised when memory privacy configuration parameters are invalid."""
