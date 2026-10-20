"""Connection pool data models, metrics, and startup backoff circuit breaker.

[INPUT]
- session_actor::MCPSessionActor (POS: MCP persistent-session layer)

[OUTPUT]
- ConnectionStatus: connection lifecycle state enum
- ConnectionMetrics: usage and latency counters
- MCPStartupBackoff: OpenClaw-style per-config exponential backoff circuit breaker
- MCPConnection: warm per-config connection wrapper holding per-server session actors

[POS]
Internal support module for ``connection_manager.py``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from .session_actor import MCPSessionActor


class ConnectionStatus(Enum):
    """Connection state."""

    IDLE = "idle"
    ACTIVE = "active"
    UNHEALTHY = "unhealthy"
    CLOSED = "closed"


class MCPServerState(Enum):
    """Granular MCP server runtime lifecycle state.

    6-state model:
    - CONNECTED: warm session ready and healthy
    - CONNECTING: startup or reconnecting in progress
    - UNCONFIGURED: server not configured or inactive
    - OFFLINE: configured but idle / not started
    - AUTH_REQUIRED: credentials missing or auth expired
    - ERROR: failed to start or circuit breaker active
    """

    CONNECTED = "connected"
    CONNECTING = "connecting"
    UNCONFIGURED = "unconfigured"
    OFFLINE = "offline"
    AUTH_REQUIRED = "auth_required"
    ERROR = "error"


@dataclass
class ConnectionMetrics:
    """Connection usage metrics."""

    created_at: float
    last_used: float
    use_count: int
    total_time: float
    error_count: int
    total_tokens_consumed: int = 0
    last_error: str | None = None


_BACKOFF_SCHEDULE_SECONDS: tuple[float, ...] = (1.0, 5.0, 15.0, 60.0)


@dataclass(slots=True)
class _BackoffEntry:
    failures: int
    cooldown_until: float
    last_error: str
    server_names: tuple[str, ...]


class MCPStartupBackoff:
    """Tracks consecutive startup failures per ``config_hash`` with exponential cooldown.

    Schedule: ``1s -> 5s -> 15s -> max 60s``. Prevents dead or misconfigured MCP
    servers from repeatedly blocking concurrent agent requests while allowing
    immediate recovery on ``refresh_server_auth`` or manual reset.
    """

    def __init__(self, schedule: tuple[float, ...] = _BACKOFF_SCHEDULE_SECONDS) -> None:
        self._schedule = schedule
        self._entries: dict[str, _BackoffEntry] = {}

    def check_allowed(self, config_hash: str) -> None:
        """Raise ``RuntimeError`` if *config_hash* is currently in its cooldown window."""
        entry = self._entries.get(config_hash)
        if entry is None:
            return
        remaining = entry.cooldown_until - time.monotonic()
        if remaining > 0:
            raise RuntimeError(
                f"MCP connection {config_hash[:12]} in startup backoff cooldown "
                f"({remaining:.1f}s remaining after {entry.failures} failure(s)): {entry.last_error}"
            )

    def record_failure(
        self,
        config_hash: str,
        error_detail: str,
        server_names: tuple[str, ...] = (),
    ) -> float:
        """Record a failed startup and return the applied cooldown in seconds."""
        prev = self._entries.get(config_hash)
        failures = (prev.failures + 1) if prev is not None else 1
        idx = min(failures - 1, len(self._schedule) - 1)
        delay = self._schedule[idx]
        self._entries[config_hash] = _BackoffEntry(
            failures=failures,
            cooldown_until=time.monotonic() + delay,
            last_error=error_detail,
            server_names=server_names or (prev.server_names if prev is not None else ()),
        )
        return delay

    def record_success(self, config_hash: str) -> None:
        """Clear backoff state for *config_hash* after a successful startup."""
        self._entries.pop(config_hash, None)

    def clear_server(self, server_name: str) -> None:
        """Clear backoff entries involving *server_name* (e.g. on auth refresh)."""
        to_remove = [
            key for key, entry in self._entries.items() if not entry.server_names or server_name in entry.server_names
        ]
        for key in to_remove:
            self._entries.pop(key, None)

    def clear_all(self) -> None:
        """Reset all backoff entries."""
        self._entries.clear()


class MCPConnection:
    """A warm connection for one config — one session actor per server.

    Holds persistent, already-initialized sessions and routes tool calls to the
    owning actor so the underlying process/connection is reused across calls.
    """

    def __init__(
        self,
        config_hash: str,
        actors: dict[str, MCPSessionActor],
    ) -> None:
        self.config_hash = config_hash
        self._actors = actors
        self.status = ConnectionStatus.IDLE
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        now = time.time()
        self.metrics = ConnectionMetrics(
            created_at=now,
            last_used=now,
            use_count=0,
            total_time=0.0,
            error_count=0,
        )

    def is_bound_to_current_loop(self) -> bool:
        """True if this connection's actors live on the currently running loop."""
        try:
            return self._loop is asyncio.get_running_loop()
        except RuntimeError:
            return False

    @property
    def tools_by_server(self) -> dict[str, list[BaseTool]]:
        """Actor-routed proxy tools grouped by server (schemas for routing/skills)."""
        return {name: actor.tools for name, actor in self._actors.items()}

    @property
    def instructions_by_server(self) -> dict[str, str | None]:
        """MCP ``initialize`` instructions per server, captured once at startup."""
        return {name: actor.instructions for name, actor in self._actors.items()}

    def _resolve_actor(self, server_name: str) -> MCPSessionActor | None:
        actor = self._actors.get(server_name)
        if actor is not None:
            return actor
        for variant in (server_name.replace("-", "_"), server_name.replace("_", "-")):
            actor = self._actors.get(variant)
            if actor is not None:
                return actor
        return None

    async def call(self, server_name: str, tool_name: str, params: dict[str, object]) -> object:
        """Invoke a tool on the warm session of the given server."""
        actor = self._resolve_actor(server_name)
        if actor is None:
            raise RuntimeError(f"MCP server not found: {server_name}. Available servers: {list(self._actors)}")

        self.status = ConnectionStatus.ACTIVE
        self.metrics.use_count += 1
        self.metrics.last_used = time.time()
        start = time.time()
        try:
            return await actor.call(tool_name, params)
        except Exception:
            self.metrics.error_count += 1
            if not actor.is_healthy():
                self.status = ConnectionStatus.UNHEALTHY
            raise
        finally:
            self.metrics.total_time += time.time() - start
            if self.status == ConnectionStatus.ACTIVE:
                self.status = ConnectionStatus.IDLE

    async def read_resource(self, server_name: str, uri: str) -> bytes:
        """Read a resource from the given MCP server's warm session."""
        actor = self._resolve_actor(server_name)
        if actor is None:
            raise RuntimeError(f"MCP server not found: {server_name}. Available servers: {list(self._actors)}")

        self.metrics.last_used = time.time()
        return await actor.read_resource(uri)

    async def health_check(self) -> bool:
        """Return True only if every server's session is alive and usable."""
        if self.status == ConnectionStatus.CLOSED:
            return False
        healthy = bool(self._actors) and all(actor.is_healthy() for actor in self._actors.values())
        if not healthy:
            self.status = ConnectionStatus.UNHEALTHY
        return healthy

    def is_expired(self, ttl: int) -> bool:
        """Check whether the connection has been idle longer than ``ttl``."""
        last = self.metrics.last_used
        if self._actors:
            last = max(last, *(actor.last_activity for actor in self._actors.values()))
        return time.time() - last > ttl

    def get_stats(self) -> dict[str, object]:
        """Return connection statistics for observability."""
        now = time.time()
        return {
            "status": self.status.value,
            "servers": list(self._actors),
            "age_seconds": int(now - self.metrics.created_at),
            "idle_seconds": int(now - self.metrics.last_used),
            "use_count": self.metrics.use_count,
            "avg_time_ms": int(self.metrics.total_time * 1000 / max(1, self.metrics.use_count)),
            "error_count": self.metrics.error_count,
            "error_rate": f"{self.metrics.error_count / max(1, self.metrics.use_count) * 100:.1f}%",
        }

    def refresh_server_auth(self, server_name: str, new_headers: dict[str, str]) -> bool:
        """Hot-update auth headers for a specific server's session actor."""
        actor = self._resolve_actor(server_name)
        if actor is None:
            return False
        actor.update_auth_headers(new_headers)
        return True

    def get_server_state(self, server_name: str) -> MCPServerState:
        """Derive the fine-grained 6-state status for a specific MCP server."""
        if self.status == ConnectionStatus.CLOSED:
            return MCPServerState.OFFLINE
        actor = self._resolve_actor(server_name)
        if actor is None:
            return MCPServerState.UNCONFIGURED
        if not actor.is_healthy():
            start_err = getattr(actor, "_start_error", None)
            if start_err and "auth" in str(start_err).lower():
                return MCPServerState.AUTH_REQUIRED
            return MCPServerState.ERROR
        return MCPServerState.CONNECTED

    async def close(self) -> None:
        """Close every session actor, releasing all processes / connections."""
        if self.status == ConnectionStatus.CLOSED:
            return
        self.status = ConnectionStatus.CLOSED
        await asyncio.gather(
            *(actor.close() for actor in self._actors.values()),
            return_exceptions=True,
        )
        self._actors.clear()
