"""Data types and schemas for Docker Sandbox 8-Flag Hardening and Vault-Proxy Suite."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class NetworkIsolationMode(StrEnum):
    """Network isolation modes for sandbox container."""

    NONE = "none"
    HOST = "host"
    BRIDGE_RESTRICTED = "bridge_restricted"


class ProvisionStatus(StrEnum):
    """Lifecycle status of a sandboxed runner."""

    UNINITIALIZED = "uninitialized"
    WARM = "warm"
    RUNNING = "running"
    DISPOSED = "disposed"


@dataclass(frozen=True)
class EightFlagSandboxConfig:
    """The 8-Flag physical container hardening configuration matrix.

    Flags:
    1. read_only: Root filesystem is strictly read-only.
    2. tmpfs_noexec: /tmp mounted in RAM with noexec flag.
    3. pids_limit: Maximum process tree count to block fork-bombs.
    4. cap_drop_all: Complete drop of Linux capabilities.
    5. no_new_privileges: Block setuid escalation.
    6. non_root_user: Run as unprivileged UID:GID (e.g., 1000:1000).
    7. network_mode: Default to 'none' physical air-gap.
    8. memory_limit & cpu_quota: Strict hardware boundary.
    """

    read_only: bool = True
    tmp_size_mb: int = 100
    tmp_noexec: bool = True
    pids_limit: int = 100
    cap_drop_all: bool = True
    no_new_privileges: bool = True
    user: str = "1000:1000"
    network_mode: NetworkIsolationMode = NetworkIsolationMode.NONE
    memory_limit: str = "512m"
    cpus_quota: float = 1.0
    auto_remove: bool = True


@dataclass(frozen=True)
class HardenedDockerCommand:
    """Computed Docker CLI run arguments and security flags."""

    raw_args: list[str]
    flags_verified: bool
    missing_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VaultCredentialEntry:
    """Host-managed credential entry that never enters container filesystem or env."""

    credential_id: str
    target_service: str
    secret_value: str
    allowed_domains: list[str]
    description: str = ""


@dataclass(frozen=True)
class VaultProxyRequest:
    """Outbound proxy request from sandbox with placeholder token."""

    project_id: str
    target_url: str
    method: str
    credential_id: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str = ""


@dataclass(frozen=True)
class VaultProxyResponse:
    """Response returned through host proxy gateway."""

    status_code: int
    headers: Mapping[str, str]
    body: str
    credential_injected: bool
    blocked_reason: str | None = None
