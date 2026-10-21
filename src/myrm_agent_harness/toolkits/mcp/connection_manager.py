"""MCP connection manager — persistent warm-session pool.

Architecture:
- Global singleton, initialized at app startup, cleaned up at process exit
- One :class:`MCPConnection` per distinct config hash; each holds one
  :class:`MCPSessionActor` per server (a warm, already-initialized session)
- Per-``config_hash`` singleflight creation locks so distinct MCP servers spawn
  in parallel without head-of-line blocking, bounded by a process-wide spawn
  semaphore
- OpenClaw-style exponential startup backoff circuit breaker (``MCPStartupBackoff``)
- Transparent cross-TTL proxy tool rebinding via ``actor_resolver``

[INPUT]
- client::MCPClientManager, MCPServerConfigProtocol (POS: MCP client management layer)
- session_actor::MCPSessionActor (POS: MCP persistent-session layer)
- placeholders::resolve_stdio_launch (POS: MCP stdio env/cwd/placeholder resolution)
- connection_pool_types (POS: ConnectionStatus, ConnectionMetrics, MCPConnection, MCPStartupBackoff)

[OUTPUT]
- MCPConnection: warm per-config connection
- MCPConnectionManager: persistent pool with per-hash singleflight, startup backoff, and TTL recycling
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
import weakref
from contextlib import suppress
from typing import TYPE_CHECKING

from .connection_pool_types import (
    ConnectionMetrics,
    ConnectionStatus,
    MCPConnection,
    MCPServerState,
    MCPStartupBackoff,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .client import MCPServerConfigProtocol
    from .session_actor import MCPSessionActor
    from .session_actor_types import MCPActorResolver

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_SPAWNS = 8


class MCPConnectionManager:
    """Global singleton pool of warm MCP connections."""

    _instance: MCPConnectionManager | None = None
    _init_lock = asyncio.Lock()

    def __init__(self, ttl: int = 600, cleanup_interval: int = 60) -> None:
        self._connections: dict[str, MCPConnection] = {}
        self._ttl = ttl
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task[None] | None = None
        self._started = False
        self._create_lock = asyncio.Lock()
        self._create_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._spawn_semaphore: asyncio.Semaphore | None = None
        self._create_lock_loop: asyncio.AbstractEventLoop | None = None
        self._backoff = MCPStartupBackoff()
        logger.info("[MCPConnectionManager] Initialized")

    def _sync_loop_primitives(self) -> None:
        """Reset loop-bound locks and semaphores when the running event loop changes."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._create_lock_loop is not loop:
            self._create_lock = asyncio.Lock()
            self._create_locks.clear()
            self._spawn_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SPAWNS)
            self._create_lock_loop = loop

    def _get_create_lock(self, config_hash: str | None = None) -> asyncio.Lock:
        """Return a per-``config_hash`` singleflight creation lock bound to the running loop."""
        self._sync_loop_primitives()
        if config_hash is None:
            return self._create_lock
        lock = self._create_locks.get(config_hash)
        if lock is None:
            lock = asyncio.Lock()
            self._create_locks[config_hash] = lock
        return lock

    def _get_spawn_semaphore(self) -> asyncio.Semaphore:
        """Return a loop-bound semaphore capping concurrent server startups."""
        self._sync_loop_primitives()
        if self._spawn_semaphore is None:
            self._spawn_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SPAWNS)
        return self._spawn_semaphore

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
        """Hash the full effective config so distinct configs never collide."""
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
                "host_serial": getattr(s, "host_serial", False),
                "keepalive_interval": getattr(s, "keepalive_interval", None),
                "ssl_verify": getattr(s, "ssl_verify", None),
                "client_cert": getattr(s, "client_cert", None),
                "client_key": getattr(s, "client_key", None),
            }
            for s in sorted(config, key=lambda x: x.name)
        ]
        config_json = json.dumps(config_data, sort_keys=True, default=str)
        return hashlib.sha256(config_json.encode()).hexdigest()

    async def get_connection(
        self,
        config: Sequence[MCPServerConfigProtocol],
    ) -> MCPConnection:
        """Get (or lazily create) the warm connection for ``config``."""
        self._ensure_cleanup_running()
        config_hash = self._make_config_hash(config)

        existing = self._connections.get(config_hash)
        if existing is not None:
            if not existing.is_bound_to_current_loop():
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

        async with self._get_create_lock(config_hash):
            existing = self._connections.get(config_hash)
            if existing is not None and existing.is_bound_to_current_loop() and await existing.health_check():
                return existing
            self._backoff.check_allowed(config_hash)
            async with self._get_spawn_semaphore():
                try:
                    conn = await self._create_connection(config, config_hash)
                except Exception as exc:
                    server_names = tuple(cfg.name for cfg in config)
                    self._backoff.record_failure(config_hash, str(exc), server_names)
                    raise
                self._backoff.record_success(config_hash)
                return conn

    def _make_actor_resolver(
        self,
        config: Sequence[MCPServerConfigProtocol],
        server_name: str,
    ) -> MCPActorResolver:
        """Build a lazy resolver that re-acquires a warm actor after TTL eviction."""
        config_snapshot = list(config)

        async def _resolve() -> MCPSessionActor | None:
            conn = await self.get_connection(config_snapshot)
            return conn._resolve_actor(server_name)

        return _resolve

    async def _create_connection(
        self,
        config: Sequence[MCPServerConfigProtocol],
        config_hash: str,
    ) -> MCPConnection:
        """Spin up one warm session actor per server and pool the connection."""
        from .client import MCPClientManager
        from .session_actor import MCPSessionActor

        logger.info("[MCPConnectionManager] Creating connection: %s", config_hash[:16])

        spawned_actors: list[MCPSessionActor] = []

        async def _spawn(cfg: MCPServerConfigProtocol) -> tuple[str, MCPSessionActor]:
            await MCPClientManager._inject_auth_headers_into_config(cfg)
            from .placeholders import resolve_stdio_launch

            extra_params = getattr(cfg, "extra_params", None)
            command, args, stdio_env, stdio_cwd = resolve_stdio_launch(
                cfg.command,
                cfg.args,
                extra_params if isinstance(extra_params, dict) else None,
            )
            plugin_root = (
                extra_params.get("plugin_root")
                if isinstance(extra_params, dict) and isinstance(extra_params.get("plugin_root"), str)
                else None
            )
            conn_dict: dict[str, object] = {
                "transport": cfg.type,
                "url": cfg.url,
                "headers": MCPClientManager.get_headers(cfg),
                "command": command,
                "args": args,
                "env": stdio_env,
                "cwd": stdio_cwd,
            }
            if plugin_root is not None:
                conn_dict["plugin_root"] = plugin_root
            for tls_key in ("ssl_verify", "client_cert", "client_key", "client_key_password"):
                tls_val = getattr(cfg, tls_key, None)
                if tls_val is not None:
                    conn_dict[tls_key] = tls_val

            actor = MCPSessionActor(
                cfg.name,
                conn_dict,
                connect_timeout=getattr(cfg, "connect_timeout", 15.0),
                execute_timeout=getattr(cfg, "execute_timeout", 120.0),
                max_output_chars=getattr(cfg, "max_output_chars", 100_000),
                tool_include=getattr(cfg, "tool_include", None),
                tool_exclude=getattr(cfg, "tool_exclude", None),
                host_serial=getattr(cfg, "host_serial", False),
                keepalive_interval=getattr(cfg, "keepalive_interval", None),
                auth_provider=getattr(cfg, "auth_provider", None),
                oversized_result_handler=getattr(cfg, "oversized_result_handler", None),
                elicitation_handler=getattr(cfg, "elicitation_handler", None),
                actor_resolver=self._make_actor_resolver(config, cfg.name),
            )
            await actor.start()
            spawned_actors.append(actor)
            return cfg.name, actor

        actors: dict[str, MCPSessionActor] = {}
        try:
            results = await asyncio.gather(*(_spawn(cfg) for cfg in config), return_exceptions=True)

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
        except BaseException:
            if spawned_actors:
                await asyncio.gather(*(actor.close() for actor in spawned_actors), return_exceptions=True)
            raise

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
        """Close every pooled connection and reset backoff state."""
        logger.info(
            "[MCPConnectionManager] Closing all connections (%d total)",
            len(self._connections),
        )
        await asyncio.gather(
            *(conn.close() for conn in self._connections.values()),
            return_exceptions=True,
        )
        self._connections.clear()
        self._backoff.clear_all()

    def refresh_server_auth(self, server_name: str, new_headers: dict[str, str]) -> bool:
        """Hot-update auth headers for a named server and reset any startup backoff."""
        self._backoff.clear_server(server_name)
        updated = False
        for conn in self._connections.values():
            if conn.status != ConnectionStatus.CLOSED and conn.refresh_server_auth(server_name, new_headers):
                updated = True
        if updated:
            logger.info("[MCPConnectionManager] Auth headers refreshed for server '%s'", server_name)
        return updated

    def get_stats(self) -> dict[str, object]:
        """Return pool-wide statistics for observability."""
        return {
            "total_connections": len(self._connections),
            "started": self._started,
            "ttl": self._ttl,
            "connections": {config_hash[:16]: conn.get_stats() for config_hash, conn in self._connections.items()},
        }

    def get_server_runtime_status(self, server_name: str) -> dict[str, object]:
        """Query granular runtime status for an MCP server across active connections.

        Returns standard MCPServerState and execution metrics.
        """
        for conn in self._connections.values():
            if conn.status == ConnectionStatus.CLOSED:
                continue
            actor = conn._resolve_actor(server_name)
            if actor is not None:
                state = conn.get_server_state(server_name)
                return {
                    "server_name": server_name,
                    "state": state.value,
                    "healthy": actor.is_healthy(),
                    "tool_count": len(actor.tools),
                    "use_count": conn.metrics.use_count,
                    "error_count": conn.metrics.error_count,
                    "total_tokens_consumed": conn.metrics.total_tokens_consumed,
                    "last_used": conn.metrics.last_used,
                    "last_error": conn.metrics.last_error,
                }

        for entry in self._backoff._entries.values():
            if server_name in entry.server_names:
                remaining = max(0.0, entry.cooldown_until - time.monotonic())
                if remaining > 0:
                    return {
                        "server_name": server_name,
                        "state": MCPServerState.ERROR.value,
                        "healthy": False,
                        "tool_count": 0,
                        "cooldown_remaining_seconds": round(remaining, 1),
                        "last_error": entry.last_error,
                    }

        return {
            "server_name": server_name,
            "state": MCPServerState.OFFLINE.value,
            "healthy": False,
            "tool_count": 0,
            "use_count": 0,
            "error_count": 0,
            "total_tokens_consumed": 0,
        }

    def __repr__(self) -> str:
        return f"<MCPConnectionManager connections={len(self._connections)} started={self._started}>"


async def get_mcp_connection_manager() -> MCPConnectionManager:
    """Get the global MCP connection manager singleton."""
    return await MCPConnectionManager.get_instance()


async def get_mcp_connection(
    config: Sequence[MCPServerConfigProtocol],
) -> MCPConnection:
    """Acquire a warm pooled connection for the given MCP config."""
    manager = await get_mcp_connection_manager()
    return await manager.get_connection(config)


__all__ = [
    "ConnectionMetrics",
    "ConnectionStatus",
    "MCPConnection",
    "MCPConnectionManager",
    "MCPServerState",
    "MCPStartupBackoff",
    "get_mcp_connection",
    "get_mcp_connection_manager",
]
