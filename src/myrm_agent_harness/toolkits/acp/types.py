"""Core type definitions for the ACP runtime system.

Defines the fundamental abstractions: RuntimeBackend Protocol, RuntimeEvent,
error codes, configuration, and permission types. All other ACP runtime modules
depend on this module.


[INPUT]
no - Base type definition module

[OUTPUT]
- RuntimeBackend: Runtime Backend abstract protocol
- RuntimeEvent: Runtime Event type
- AcpErrorCode: ACP error enum
- RuntimeConfig: Runtime configuration
- PermissionMode: Permission pattern type
- PermissionDecision: Permission decision enum

[POS]
ACP runtime type definitions layer. Provides all ACP-related core abstractions and data
structures, serving as the foundation for the entire ACP module.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RuntimeEventType(StrEnum):
    """Event types emitted during a runtime turn."""

    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    PERMISSION_REQUEST = "permission_request"
    USAGE_UPDATE = "usage_update"
    STATUS_UPDATE = "status_update"
    ERROR = "error"
    DONE = "done"


class AcpErrorCode(StrEnum):
    """Structured error codes for ACP runtime operations."""

    AUTH_FAILED = "auth_failed"
    BACKEND_NOT_FOUND = "backend_not_found"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CONTEXT_OVERFLOW = "context_overflow"
    PROCESS_CRASHED = "process_crashed"
    PERMISSION_DENIED = "permission_denied"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


PermissionMode = Literal["safe", "ask", "allow_all", "bypass"]

BackendType = Literal["acp", "sdk", "cli"]

BackendStatus = Literal["ready", "starting", "error", "stopped"]

# How a delegated backend authenticates with its model provider.
# - "subscription": the backend uses its own logged-in credentials (the user's
#   ChatGPT Plus / Claude Max / Gemini subscription persisted by the CLI itself);
#   provider API keys are stripped from the child environment so the CLI is forced
#   onto its subscription session and never silently falls back to metered API billing.
# - "api_key": the host injects a specific provider key via ``RuntimeConfig.env``;
#   usage is billed per token against that key.
AuthMode = Literal["subscription", "api_key"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcpError:
    """Structured error with code, message, and retryable flag."""

    code: AcpErrorCode
    message: str
    retryable: bool = False
    details: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """A single event emitted during a runtime turn.

    For ``permission_request`` events, ``data["response_future"]`` contains an
    ``asyncio.Future[PermissionDecision]`` that the subscriber must resolve.
    """

    type: RuntimeEventType
    data: dict[str, object]
    session_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Declares what a RuntimeBackend supports."""

    supports_resume: bool = False
    supports_mcp: bool = False
    supports_streaming: bool = True
    supports_tools: bool = True


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """Runtime-queryable metadata about a backend."""

    name: str
    version: str | None = None
    backend_type: BackendType = "acp"
    status: BackendStatus = "ready"
    capabilities: BackendCapabilities = field(default_factory=BackendCapabilities)
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    """Configuration for an MCP server to inject into a runtime."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Unified configuration for any RuntimeBackend."""

    backend_type: BackendType
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    timeout_seconds: int = 300
    permission_mode: PermissionMode = "allow_all"
    allowed_tools: list[str] = field(default_factory=list)
    strip_env_keys: list[str] = field(default_factory=list)
    auth_mode: AuthMode = "subscription"
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
    max_response_chars: int = 50_000
    max_turns: int = 25
    description: str = ""


class PermissionDecision(StrEnum):
    """Possible outcomes for a permission request."""

    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY_ONCE = "deny_once"
    DENY_ALWAYS = "deny_always"


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class RuntimeBackend(Protocol):
    """Unified interface for ACP, SDK, and CLI agent backends.

    Implementations must support the full lifecycle: run_turn, cancel, resume,
    get_info, and close.
    """

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> BackendCapabilities: ...

    @property
    def is_alive(self) -> bool: ...

    async def run_turn(
        self,
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ) -> AsyncIterator[RuntimeEvent]: ...

    async def cancel(self, session_id: str) -> None: ...

    async def resume(self, session_id: str) -> bool: ...

    async def get_info(self) -> BackendInfo: ...

    async def close(self) -> None: ...


@runtime_checkable
class PermissionManager(Protocol):
    """Protocol for permission checking — framework provides default, business layer can replace."""

    async def check(
        self,
        tool_name: str,
        tool_input: dict[str, object],
        session_id: str,
    ) -> PermissionDecision: ...

    def record_approval(self, tool_name: str, session_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_event(
    event_type: RuntimeEventType,
    session_id: str,
    **data: object,
) -> RuntimeEvent:
    """Convenience factory for creating RuntimeEvent instances."""
    return RuntimeEvent(type=event_type, data=data, session_id=session_id)


def create_permission_request(
    session_id: str,
    tool_name: str,
    tool_input: dict[str, object],
) -> tuple[RuntimeEvent, asyncio.Future[PermissionDecision]]:
    """Create a permission_request event with its response Future.

    Returns:
        A (event, future) tuple. The subscriber resolves the future with a
        PermissionDecision; the runtime awaits it.
    """
    future: asyncio.Future[PermissionDecision] = asyncio.get_running_loop().create_future()
    event = RuntimeEvent(
        type=RuntimeEventType.PERMISSION_REQUEST,
        data={
            "tool_name": tool_name,
            "tool_input": tool_input,
            "response_future": future,
        },
        session_id=session_id,
    )
    return event, future
