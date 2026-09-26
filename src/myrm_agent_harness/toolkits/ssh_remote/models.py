"""Data models and specifications for SSH remote execution and SFTP transfer.

[INPUT]
- None (standard dataclasses & typing)

[OUTPUT]
- SSHHostSpec, SSHCommandResult, SFTPTransferResult, SSHAuthType

[POS]
Data contract models for ssh_remote toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SSHAuthType(str, Enum):
    """Authentication type for SSH connection."""

    PASSWORD = "password"
    PRIVATE_KEY = "private_key"
    AGENT = "agent"
    NONE = "none"


@dataclass
class SSHHostSpec:
    """Specification for connecting to a remote host."""

    host_id: str
    hostname: str
    port: int = 22
    username: str = "root"
    auth_type: SSHAuthType = SSHAuthType.PASSWORD
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None
    proxy_jump: str | None = None
    timeout_seconds: float = 30.0
    tags: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class SSHCommandResult:
    """Result of an executed remote SSH command."""

    host_id: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    distilled_output: str
    elapsed_seconds: float
    is_timeout: bool = False
    blocked_by_guard: bool = False
    block_reason: str = ""


@dataclass
class SFTPTransferResult:
    """Result of an SFTP file transfer operation."""

    host_id: str
    remote_path: str
    local_path: str
    operation: str  # "upload" or "download"
    bytes_transferred: int
    success: bool
    error_message: str = ""
    elapsed_seconds: float = 0.0
