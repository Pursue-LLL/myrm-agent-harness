"""MCP connection manager — persistent warm-session pool.

Architecture:
- Global singleton, initialized at app startup, cleaned up at process exit
- One :class:`MCPConnection` per distinct config hash; each holds one
  :class:`MCPSessionActor` per server (a warm, already-initialized session)
- Tool calls are routed to the owning actor, which executes them on the live
  session — no per-call subprocess spawn or re-``initialize`` handshake
- Actors self-heal transport breaks (reconnect in place); the pool's health
  check + rebuild is only the last resort once an actor's reconnect budget is
  exhausted
- TTL expiry recycles idle connections

Performance model (the real win):
- A server with heavy startup (large catalog, DB pool, model load) pays that
  cost **once** per connection lifetime instead of once per tool call.
- SSE/HTTP servers reuse a single connection instead of reconnecting per call,
  cutting latency and transient handshake failures.

[INPUT]
- client::MCPClientManager, MCPServerConfigProtocol (POS: MCP client management layer)
- session_actor::MCPSessionActor (POS: MCP persistent-session layer)

[OUTPUT]
- MCPConnection: warm per-config connection (a set of per-server session actors)
- MCPConnectionManager: persistent pool with health checks and TTL expiry
- get_mcp_connection_manager(): global singleton accessor
- get_mcp_connection(): acquire a pooled connection for a config

[POS]
MCP connection pool layer. Manages persistent MCP sessions with health
monitoring and TTL recycling, delivering true per-call connection reuse.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.tools import BaseTool

    from .client import MCPServerConfigProtocol
    from .session_actor import MCPSessionActor

logger = logging.getLogger(__name__)


class ConnectionStatus(Enum):
    """Connection state."""

    IDLE = "idle"  # Available
    ACTIVE = "active"  # In use
    UNHEALTHY = "unhealthy"  # Broken — will be recycled
    CLOSED = "closed"  # Closed


@dataclass
class ConnectionMetrics:
    """Connection usage metrics."""

    created_at: float
    last_used: float
    use_count: int
    total_time: float  # Cumulative tool-call time
    error_count: int


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
        # Actors pin their owner task (and asyncio.Queue/Future) to the loop that
        # created them; a connection is only reusable on that same loop. Reuse
        # from a different loop (e.g. a new per-test loop) must rebuild instead.
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
        """Read a resource from the given MCP server's warm session.

        Used by MCP Apps (ext-apps) host to fetch UI content.
        """
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
        """Check whether the connection has been idle longer than ``ttl``.

        Idle time is measured against the most recent activity from *either*
        path: ``metrics.last_used`` (PTC via ``call``) and each actor's
        ``last_activity`` (direct-mode tools invoked straight on the actor).
        """
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


class MCPConnectionManager:
    """Global singleton pool of warm MCP connections.

    Design principles:
    - Singleton: one instance per process
    - Lazy: connections (and their sessions) created on demand
    - Auto-recycle: TTL-expired and unhealthy connections are closed and rebuilt
    """

    _instance: MCPConnectionManager | None = None
    _init_lock = asyncio.Lock()

    def __init__(self, ttl: int = 600, cleanup_interval: int = 60) -> None:
        self._connections: dict[str, MCPConnection] = {}
        self._ttl = ttl
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task[None] | None = None
        self._started = False
        self._create_lock = asyncio.Lock()
        self._create_lock_loop: asyncio.AbstractEventLoop | None = None
        logger.info("[MCPConnectionManager] Initialized")

    def _get_create_lock(self) -> asyncio.Lock:
        """Return a creation lock bound to the running loop.

        The singleton outlives individual event loops (e.g. per-test loops); an
        ``asyncio.Lock`` is loop-bound once contended, so we recreate it whenever
        the loop changes to avoid cross-loop "bound to a different loop" errors.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._create_lock
        if self._create_lock_loop is not loop:
            self._create_lock = asyncio.Lock()
            self._create_lock_loop = loop
        return self._create_lock

    def _ensure_cleanup_running(self) -> None:
        """Restart the TTL cleanup task if it died with a previous event loop."""
        if not self._started:
            return
        task = self._cleanup_task
        if task is None or task.done():
            with suppress(RuntimeError):
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    @classmethod
    async def get_instance(cls) -> MCPConnectionManager:
        """Return the global singleton, starting it on first access."""
        if cls._instance is None:
            async with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance.start()
        return cls._instance

    async def start(self) -> None:
        """Start the background TTL cleanup loop."""
        if self._started:
            return
        self._started = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("[MCPConnectionManager] Cleanup task started")

    async def stop(self) -> None:
        """Stop the cleanup loop and close all connections."""
        if not self._started:
            return
        self._started = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None
        await self.close_all()
        logger.info("[MCPConnectionManager] Stopped")

    def _make_config_hash(self, config: Sequence[MCPServerConfigProtocol]) -> str:
        """Hash the full effective config so distinct configs never collide.

        Includes every field that changes the established session or its tool
        surface (command/args/url/headers/extra_params + the tool filter), not
        just name/type — two servers differing only in args must not share a
        pooled connection.
        """
        config_data = [
            {
                "name": s.name,
                "type": s.type,
                "command": s.command if s.type == "stdio" else None,
                "args": s.args if s.type == "stdio" else None,
                "url": s.url if s.type in ("sse", "streamable_http") else None,
                "headers": getattr(s, "headers", None),
                "extra_params": getattr(s, "extra_params", None),
                "tool_include": getattr(s, "tool_include", None),
                "tool_exclude": getattr(s, "tool_exclude", None),
            }
            for s in sorted(config, key=lambda x: x.name)
        ]
        config_json = json.dumps(config_data, sort_keys=True, default=str)
        return hashlib.sha256(config_json.encode()).hexdigest()

    async def get_connection(
        self,
        config: Sequence[MCPServerConfigProtocol],
    ) -> MCPConnection:
        """Get (or lazily create) the warm connection for ``config``.

        Reuses a healthy pooled connection with the same effective config; a
        connection found unhealthy is closed and rebuilt transparently.
        """
        self._ensure_cleanup_running()
        config_hash = self._make_config_hash(config)

        existing = self._connections.get(config_hash)
        if existing is not None:
            if not existing.is_bound_to_current_loop():
                # The owning event loop changed; the old actors are pinned to a
                # now-defunct loop (their tasks already finalised at loop close),
                # so drop the stale entry and rebuild on the current loop.
                logger.info(
                    "[MCPConnectionManager] Event loop changed; rebuilding connection %s",
                    config_hash[:16],
                )
                self._connections.pop(config_hash, None)
            elif await existing.health_check():
                logger.info(
                    "[MCPConnectionManager] Reusing connection %s (used %d, age %ds)",
                    config_hash[:16],
                    existing.metrics.use_count,
                    int(time.time() - existing.metrics.created_at),
                )
                return existing
            else:
                logger.warning(
                    "[MCPConnectionManager] Connection unhealthy, recreating: %s",
                    config_hash[:16],
                )
                await existing.close()
                self._connections.pop(config_hash, None)

        # Serialise creation so concurrent first-callers don't spawn duplicate
        # sessions for the same config (double-check after acquiring the lock).
        async with self._get_create_lock():
            existing = self._connections.get(config_hash)
            if existing is not None and existing.is_bound_to_current_loop() and await existing.health_check():
                return existing
            return await self._create_connection(config, config_hash)

    async def _create_connection(
        self,
        config: Sequence[MCPServerConfigProtocol],
        config_hash: str,
    ) -> MCPConnection:
        """Spin up one warm session actor per server and pool the connection."""
        from .client import MCPClientManager
        from .session_actor import MCPSessionActor

        logger.info("[MCPConnectionManager] Creating connection: %s", config_hash[:16])

        async def _spawn(cfg: MCPServerConfigProtocol) -> tuple[str, MCPSessionActor]:
            conn_dict = MCPClientManager.convert_server_config_to_client_format(cfg)
            await MCPClientManager._inject_auth_headers(cfg, conn_dict)
            actor = MCPSessionActor(
                cfg.name,
                conn_dict,
                connect_timeout=getattr(cfg, "connect_timeout", 15.0),
                execute_timeout=getattr(cfg, "execute_timeout", 120.0),
                tool_include=getattr(cfg, "tool_include", None),
                tool_exclude=getattr(cfg, "tool_exclude", None),
            )
            await actor.start()
            return cfg.name, actor

        results = await asyncio.gather(*(_spawn(cfg) for cfg in config), return_exceptions=True)

        actors: dict[str, MCPSessionActor] = {}
        errors: list[str] = []
        for result in results:
            if isinstance(result, BaseException):
                errors.append(str(result))
                continue
            name, actor = result
            actors[name] = actor

        if not actors:
            raise RuntimeError(f"All MCP servers failed to start: {'; '.join(errors)}")
        if errors:
            logger.warning(
                "[MCPConnectionManager] %d/%d MCP server(s) failed to start: %s",
                len(errors),
                len(results),
                "; ".join(errors),
            )

        conn = MCPConnection(config_hash, actors)
        self._connections[config_hash] = conn
        total_tools = sum(len(actor.tools) for actor in actors.values())
        logger.info(
            "[MCPConnectionManager] Connection ready: %s (servers: %d, tools: %d)",
            config_hash[:16],
            len(actors),
            total_tools,
        )
        return conn

    async def _cleanup_loop(self) -> None:
        """Background loop that recycles idle (TTL-expired) connections."""
        while self._started:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[MCPConnectionManager] Cleanup error: %s", e)

    async def _cleanup_expired(self) -> None:
        """Close and drop connections idle beyond the TTL."""
        expired = [config_hash for config_hash, conn in self._connections.items() if conn.is_expired(self._ttl)]
        for config_hash in expired:
            conn = self._connections.pop(config_hash)
            await conn.close()
            logger.info(
                "[MCPConnectionManager] Expired connection cleaned: %s (used %d times)",
                config_hash[:16],
                conn.metrics.use_count,
            )
        if expired:
            logger.info("[MCPConnectionManager] Cleaned %d expired connections", len(expired))

    async def close_all(self) -> None:
        """Close every pooled connection."""
        logger.info(
            "[MCPConnectionManager] Closing all connections (%d total)",
            len(self._connections),
        )
        await asyncio.gather(
            *(conn.close() for conn in self._connections.values()),
            return_exceptions=True,
        )
        self._connections.clear()

    def get_stats(self) -> dict[str, object]:
        """Return pool-wide statistics for observability."""
        return {
            "total_connections": len(self._connections),
            "started": self._started,
            "ttl": self._ttl,
            "connections": {config_hash[:16]: conn.get_stats() for config_hash, conn in self._connections.items()},
        }

    def __repr__(self) -> str:
        return f"<MCPConnectionManager connections={len(self._connections)} started={self._started}>"


# ============================================================================
# Convenience access functions
# ============================================================================


async def get_mcp_connection_manager() -> MCPConnectionManager:
    """Get the global MCP connection manager singleton."""
    return await MCPConnectionManager.get_instance()


async def get_mcp_connection(
    config: Sequence[MCPServerConfigProtocol],
) -> MCPConnection:
    """Acquire a warm pooled connection for the given MCP config."""
    manager = await get_mcp_connection_manager()
    return await manager.get_connection(config)
