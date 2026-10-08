"""
[POS] src/myrm_agent_harness/core/security/hardened_sandbox_perimeter/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] SandboxIsolationModeEnum, EgressVerdictEnum, RuntimeSpecValidationVerdictEnum, HardenedSandboxSpec, RuntimeSpecValidationResult, EgressTarget, EgressEvaluationResult, BrokerCredentialTicket, ProcessUsageSnapshot, SandboxSafetyMetrics

Data types and specifications for Scale-Ready Hardened Agent Sandbox & Safety Perimeter Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SandboxIsolationModeEnum(StrEnum):
    """Underlying sandboxing isolation technology."""

    CONTAINER = "CONTAINER"
    MICRO_VM = "MICRO_VM"
    PROCESS_JAIL = "PROCESS_JAIL"


class EgressVerdictEnum(StrEnum):
    """Decision verdict for outbound network traffic."""

    ALLOWED = "ALLOWED"
    BLOCKED_PRIVATE_IP = "BLOCKED_PRIVATE_IP"
    BLOCKED_CLOUD_METADATA = "BLOCKED_CLOUD_METADATA"
    BLOCKED_DOMAIN_NOT_ALLOWLISTED = "BLOCKED_DOMAIN_NOT_ALLOWLISTED"
    BLOCKED_INVALID_HOST = "BLOCKED_INVALID_HOST"


class RuntimeSpecValidationVerdictEnum(StrEnum):
    """Decision verdict for sandbox startup parameter hardening."""

    VALID = "VALID"
    INVALID_ROOT_USER = "INVALID_ROOT_USER"
    INVALID_WRITABLE_ROOTFS = "INVALID_WRITABLE_ROOTFS"
    INVALID_MISSING_TMPFS_NOEXEC = "INVALID_MISSING_TMPFS_NOEXEC"
    INVALID_NO_PERSISTENT_VOLUME = "INVALID_NO_PERSISTENT_VOLUME"
    INVALID_RESOURCE_BOUNDS = "INVALID_RESOURCE_BOUNDS"


@dataclass(frozen=True)
class HardenedSandboxSpec:
    """Rigid operational parameters required to spawn a scale-ready hardened sandbox."""

    isolation_mode: SandboxIsolationModeEnum = SandboxIsolationModeEnum.CONTAINER
    is_non_root: bool = True
    uid: int = 1000
    gid: int = 1000
    read_only_rootfs: bool = True
    tmpfs_noexec: bool = True
    persistent_volume_path: str = "/workspace"
    memory_limit_mb: int = 512
    cpu_quota_pct: float = 1.0
    pids_max: int = 128


@dataclass(frozen=True)
class RuntimeSpecValidationResult:
    """Outcome of validating sandbox isolation specifications against production guidelines."""

    is_valid: bool
    verdict: RuntimeSpecValidationVerdictEnum
    violations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EgressTarget:
    """Outbound target host and port to evaluate before connecting."""

    host: str
    port: int = 443
    scheme: str = "https"


@dataclass(frozen=True)
class EgressEvaluationResult:
    """Security assessment of outbound connection attempt."""

    is_allowed: bool
    verdict: EgressVerdictEnum
    reason: str
    resolved_ip: str | None = None


@dataclass(frozen=True)
class BrokerCredentialTicket:
    """Short-lived ephemeral authorization ticket issued by host credential broker."""

    ticket_id: str
    secret_alias: str
    ephemeral_token: str
    expires_at: float
    allowed_scopes: list[str]


@dataclass(frozen=True)
class ProcessUsageSnapshot:
    """Runtime resource telemetry sampled from sandbox cgroups v2/process tree."""

    active_pids_count: int
    memory_used_mb: float
    cpu_percent: float
    is_fork_bomb_detected: bool = False


@dataclass
class SandboxSafetyMetrics:
    """Cumulative operational metrics for hardened sandbox perimeter defenses."""

    total_spec_validations: int = 0
    spec_validation_failures: int = 0
    egress_requests_evaluated: int = 0
    ssrf_blocks: int = 0
    credential_tickets_minted: int = 0
    fork_bomb_mitigations: int = 0
