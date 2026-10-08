"""Type definitions and contracts for directory trust gate and remote memory resolution.

[INPUT]
- None.

[OUTPUT]
- Typed data models and enums for directory trust and project remote memory gating.

[POS]
- Harness core security module preventing unauthorized remote memory egress and TOCTOU drifts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TrustDecision(StrEnum):
    """Categorized outcome of project remote memory trust evaluation."""

    TRUSTED_AUTHORIZED = "TRUSTED_AUTHORIZED"
    UNTRUSTED_REMOTE_REFUSED = "UNTRUSTED_REMOTE_REFUSED"
    LOCAL_SCOPE_ONLY = "LOCAL_SCOPE_ONLY"
    NO_CONFIG_FOUND = "NO_CONFIG_FOUND"


@dataclass(frozen=True)
class ProjectMemoryConfig:
    """Project-level memory and remote telemetry configuration."""

    scope: str | None = None
    domain: str | None = None
    remote_url: str | None = None
    remote_token: str | None = None
    remote_scopes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedProjectRemote:
    """Immutable outcome of single-point project memory config resolution."""

    config_path: str | None
    config_dir: str | None
    is_directory_trusted: bool
    effective_scope: str | None
    effective_domain: str | None
    remote_url: str | None
    remote_token: str | None
    remote_scopes: list[str]
    refusal_notice: str | None
    decision: TrustDecision
