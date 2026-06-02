"""Core types for OS-level process sandboxing.

[INPUT]  (none — pure type definitions)
[OUTPUT] SandboxPolicy, SandboxMode, SandboxProvider protocol, SandboxStatus
[POS]    Foundation layer — all sandbox modules import from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class SandboxMode(StrEnum):
    """Sandbox activation strategy.

    AUTO:    detect environment capabilities; enable if available, skip in containers.
    ENABLE:  force-enable; raise if no provider available.
    DISABLE: never sandbox (NullProvider).
    """

    AUTO = "auto"
    ENABLE = "enable"
    DISABLE = "disable"


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Declarative sandbox restrictions applied at the OS level.

    writable_paths: directories the sandboxed process may write to.
                    All other paths are read-only or inaccessible.
    readable_paths: additional read-only bind-mounts (beyond default / ro-bind).
    allow_network:  whether outbound network is permitted.
    env_passthrough: env var names forwarded into the sandbox.
    """

    writable_paths: tuple[str, ...] = ()
    readable_paths: tuple[str, ...] = ()
    allow_network: bool = True
    env_passthrough: tuple[str, ...] = (
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "TERM",
        "SHELL",
        "TMPDIR",
    )


@dataclass(frozen=True, slots=True)
class SandboxStatus:
    """Runtime status of the sandbox layer."""

    enabled: bool
    provider_name: str
    reason: str = ""


@runtime_checkable
class SandboxProvider(Protocol):
    """OS-level sandbox provider (pluggable).

    Implementations wrap a shell command so that it executes inside an
    OS-level sandbox (bwrap, sandbox-exec, etc.).  The provider is called
    once when creating the persistent session process — all subsequent
    commands within that session inherit the restrictions.
    """

    @property
    def name(self) -> str:
        """Human-readable provider name (e.g. 'bwrap', 'seatbelt')."""
        ...

    def wrap_command(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
    ) -> tuple[str, tuple[str, ...]]:
        """Return (executable, args) that launch *shell_path* inside a sandbox.

        The returned command replaces the direct shell invocation in
        ``LocalPersistentSession._create_process()``.
        """
        ...

    def is_available(self) -> bool:
        """Check whether this provider can run on the current system."""
        ...
