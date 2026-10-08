"""Types and models for Desktop Host Auth & Tool Routing Micro-Isolation.

Enforces:
1. Gondolin pattern: Host retains API credentials, tool execution routed into micro-isolation.
2. Workspace boundary: strict write-through confined to project root (no ~/.ssh or /etc access).
3. Fail-closed contract: never silently degrade to unisolated host execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

JsonScalar = str | int | float | bool | None


class IsolationLevel(StrEnum):
    """Execution isolation level applied to tool commands."""

    MICRO_SANDBOX = "MICRO_SANDBOX"
    FAIL_CLOSED_BLOCKED = "FAIL_CLOSED_BLOCKED"
    UNISOLATED_OVERRIDE = "UNISOLATED_OVERRIDE"


class RoutingDestination(StrEnum):
    """Target environment where a tool invocation is routed."""

    HOST_PROCESS = "HOST_PROCESS"
    MICRO_ISOLATION_SANDBOX = "MICRO_ISOLATION_SANDBOX"


@dataclass(frozen=True)
class HostCredentialPolicy:
    """Policy defining host credential stripping and sandbox environment variables."""

    host_retained_env_keys: tuple[str, ...] = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GITHUB_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
    )
    allow_unisolated_override: bool = False


@dataclass(frozen=True)
class WorkspaceMountPolicy:
    """Workspace boundary defining permitted directory and forbidden system paths."""

    workspace_root: str
    forbidden_path_substrings: tuple[str, ...] = (
        "/.ssh",
        "/.aws",
        "/.config",
        "/etc",
        "/root",
        "/var/run",
        "/Library/Keychains",
    )


@dataclass(frozen=True)
class MicroIsolationExecutionResult:
    """Outcome of tool execution via micro-isolation router."""

    tool_name: str
    destination: RoutingDestination
    isolation_level: IsolationLevel
    workspace_root: str
    output: str
    stripped_credential_keys: tuple[str, ...]


class DesktopMicroIsolationError(Exception):
    """Base error for desktop micro-isolation domain."""


class HostCredentialLeakageError(DesktopMicroIsolationError):
    """Raised when host credentials risk leaking into unisolated sandbox execution."""


class ForbiddenWorkspaceAccessError(DesktopMicroIsolationError):
    """Raised when tool execution attempts to access paths outside the mounted workspace root."""


class MicroIsolationUnavailableError(DesktopMicroIsolationError):
    """Raised when micro-isolation provider is unavailable and fail-closed contract enforces block."""
