"""Domain types and models for Marketplace Manifest Source Pinning & Capability Contract.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing manifest items, immutable source pinning,
  capability contracts, and organization admission policies.

[POS]
- Harness core domain models based on claw/hermes-agent plugin-catalog declarative contracts
  and Claude Code enterprise admission gating.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

SHA1_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class MarketplaceTier(StrEnum):
    """Trust classification of the published package."""

    OFFICIAL = "OFFICIAL"
    VERIFIED = "VERIFIED"
    COMMUNITY = "COMMUNITY"
    UNVERIFIED = "UNVERIFIED"


class PlatformKind(StrEnum):
    """Operating system platform supported by package."""

    MACOS = "macos"
    LINUX = "linux"
    WINDOWS = "windows"
    ALL = "all"


@dataclass(frozen=True)
class CapabilityContract:
    """Declared capabilities and side effects introduced upon package installation."""

    provides_tools: tuple[str, ...] = field(default_factory=tuple)
    provides_hooks: tuple[str, ...] = field(default_factory=tuple)
    provides_middleware: tuple[str, ...] = field(default_factory=tuple)
    requires_env: tuple[str, ...] = field(default_factory=tuple)
    declared_mcp_servers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MarketplaceManifestItem:
    """Declarative marketplace manifest entry with immutable source pinning."""

    package_id: str
    name: str
    version: str
    repo_url: str
    source_sha: str
    tier: MarketplaceTier
    requires_host: str = ">=0.1.0"
    platforms: tuple[PlatformKind, ...] = (PlatformKind.ALL,)
    capabilities: CapabilityContract = field(default_factory=CapabilityContract)
    publisher: str = "community"


@dataclass(frozen=True)
class AdmissionPolicy:
    """Organization-level admission allowlist policy for marketplace packages."""

    allowed_sources: tuple[str, ...] = field(default_factory=tuple)
    allowed_tiers: tuple[MarketplaceTier, ...] = field(default_factory=tuple)
    disallowed_capabilities: tuple[str, ...] = field(default_factory=tuple)
    enforce_strict_pinning: bool = True


@dataclass(frozen=True)
class AdmissionVerdict:
    """Outcome of evaluating package manifest against admission policies."""

    is_admitted: bool
    package_id: str
    reason: str
    violations: tuple[str, ...] = field(default_factory=tuple)


class MarketplaceContractError(Exception):
    """Base exception for marketplace contract and admission errors."""


class SourcePinningMissingError(MarketplaceContractError):
    """Raised when package manifest lacks an immutable commit or digest SHA."""


class DisallowedTierError(MarketplaceContractError):
    """Raised when package tier violates organization policy allowlist."""


class DisallowedCapabilityError(MarketplaceContractError):
    """Raised when package requests forbidden capabilities."""
