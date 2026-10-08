"""Domain types and models for Agent Egress Telemetry Scraper & Enterprise DLP Guard.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing telemetry risk levels, DLP verdicts,
  egress network rules, detected signatures, and scan results.

[POS]
- Harness core security domain models preventing private prompts, user tokens,
  and corporate contextual data from silently leaking through third-party telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TelemetryRiskLevel(StrEnum):
    """Severity classification of telemetry reporting channels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DLPVerdict(StrEnum):
    """Enforcement verdict of egress DLP inspection."""

    ALLOWED = "ALLOWED"
    BLOCKED_TELEMETRY_DOMAIN = "BLOCKED_TELEMETRY_DOMAIN"
    BLOCKED_HOMOGLYPH_EVASION = "BLOCKED_HOMOGLYPH_EVASION"
    BLOCKED_CIDR_BYPASS = "BLOCKED_CIDR_BYPASS"
    BLOCKED_TELEMETRY_DEPENDENCY = "BLOCKED_TELEMETRY_DEPENDENCY"


@dataclass(frozen=True)
class TelemetrySignature:
    """Pre-compiled signature representing a known telemetry endpoint or service."""

    target_domain: str
    framework_name: str
    risk_level: TelemetryRiskLevel
    description: str


@dataclass(frozen=True)
class EgressRule:
    """Outbound network egress policy declaration."""

    destination: str
    port: int | None = None
    protocol: str = "tcp"
    description: str = ""


@dataclass(frozen=True)
class DLPScanResult:
    """Comprehensive verdict returned by the DLP scanner and policy validator."""

    is_safe: bool
    verdict: DLPVerdict
    detected_signatures: tuple[TelemetrySignature, ...] = field(default_factory=tuple)
    detected_dependencies: tuple[str, ...] = field(default_factory=tuple)
    offending_rules: tuple[EgressRule, ...] = field(default_factory=tuple)
    audit_trail: str = ""


class DLPScanViolationError(Exception):
    """Base exception for data leakage prevention policy violations."""


class TelemetryEgressBlockedError(DLPScanViolationError):
    """Raised when an egress rule attempts to route traffic to a forbidden telemetry domain."""
