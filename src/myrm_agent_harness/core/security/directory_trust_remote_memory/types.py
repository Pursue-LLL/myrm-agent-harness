"""Type definitions and models for directory trust gating and remote memory resolution.

[INPUT]
- None.

[OUTPUT]
- Typed models for directory trust status, project memory configurations, and resolved remotes.

[POS]
- Harness core security module separating local scope filtering from remote memory egress.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TrustStatus(StrEnum):
    """Trust status classification of a workspace directory."""

    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"
    ERROR_FAIL_CLOSED = "ERROR_FAIL_CLOSED"


@dataclass(frozen=True)
class RemoteMemoryConfig:
    """Outbound remote memory endpoint and credential declaration."""

    url: str
    token: str
    scopes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectMemoryConfig:
    """Declared project memory configuration extracted from a repository manifest."""

    local_scope: str | None = None
    domain: str | None = None
    remote_url: str | None = None
    remote_token: str | None = None
    remote_scopes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedProjectRemote:
    """Result of single-point directory trust evaluation and remote memory resolution."""

    config_path: str | None
    config_dir: str | None
    trust_status: TrustStatus
    is_trusted: bool
    remote_memory: RemoteMemoryConfig | None
    refused_from: str | None
    refusal_notice: str | None
    effective_scope: str | None
    is_outbound_authorized: bool
