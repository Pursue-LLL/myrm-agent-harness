"""Type definitions for Immutable Host Sandbox and Zero Blast Radius Rollback Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BlastRadiusTier(StrEnum):
    """Blast radius severity tiers for attempted host/sandbox mutations."""

    ZERO_CONTAINED = "ZERO_CONTAINED"  # Confined to ephemeral workspace, zero host side-effects
    MODERATE_MUTATION = "MODERATE_MUTATION"  # Modifies local workspace files, reversible via rollback
    CRITICAL_HOST_POLLUTION = "CRITICAL_HOST_POLLUTION"  # Attempts mutation of read-only OS paths (/usr, /etc, /System)


@dataclass(slots=True, frozen=True)
class SandboxMountSpec:
    """Read-only container and bind-mount containment specifications."""

    read_only_root: bool = True
    read_only_bind_mounts: list[str] = field(default_factory=lambda: ["/usr", "/bin", "/sbin", "/lib", "/System"])
    writable_workspace_path: str = "/workspace"
    tmpfs_mounts: list[str] = field(default_factory=lambda: ["/tmp", "/run"])
    drop_all_capabilities: bool = True


@dataclass(slots=True, frozen=True)
class CommandBlastRadiusAssessment:
    """Pre-execution assessment of shell command blast radius."""

    command: str
    tier: BlastRadiusTier
    blocked: bool
    targeted_immutable_paths: list[str] = field(default_factory=list)
    mitigation_applied: str = ""


@dataclass(slots=True, frozen=True)
class SandboxCheckpoint:
    """Atomic snapshot metadata enabling millisecond-grade zero-cost rollback."""

    checkpoint_id: str
    sandbox_id: str
    created_at: float
    description: str
    workspace_state_digest: str
    file_manifest: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RollbackResult:
    """Result of an atomic environment checkpoint rollback."""

    success: bool
    checkpoint_id: str
    restored_files_count: int
    pruned_files_count: int
    restored_at: float
    error_message: str | None = None
