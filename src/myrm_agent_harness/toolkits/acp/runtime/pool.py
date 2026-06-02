"""RuntimePool — unified pool for managing arbitrary RuntimeBackend instances.

Supports ACP, SDK, and CLI backends with config-driven registration,
concurrency control via asyncio.Semaphore, and optional health monitoring.


[INPUT]
- myrm_agent_harness.toolkits.acp.event_bus::EventBus (POS: ACP event bus layer)
- myrm_agent_harness.toolkits.acp.health_monitor::HealthMonitor (POS: runtime health monitoring layer)
- myrm_agent_harness.toolkits.acp.types::RuntimeBackend, RuntimeConfig, RuntimeEvent (POS: ACP runtime type definitions)
- myrm_agent_harness.toolkits.acp.runtime.*::AcpRuntime, CliRuntime, SdkRuntime (POS: runtime backend implementations)

[OUTPUT]
- RuntimePool: unified runtime instance pool managing multiple backend types

[POS]
Runtime pool management layer. Provides multi-backend unified management, concurrency control,
health monitoring, and config-driven registration — the central dispatcher of the runtime system.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from myrm_agent_harness.toolkits.acp.event_bus import EventBus
from myrm_agent_harness.toolkits.acp.health_monitor import HealthMonitor
from myrm_agent_harness.toolkits.acp.types import (
    RuntimeBackend,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeEventType,
)

logger = logging.getLogger(__name__)


def _create_runtime(
    name: str,
    config: RuntimeConfig,
    *,
    event_bus: EventBus | None = None,
) -> RuntimeBackend:
    """Factory: create the appropriate RuntimeBackend based on config.backend_type."""
    if config.backend_type == "acp":
        from myrm_agent_harness.toolkits.acp.runtime.acp_runtime import AcpRuntime

        return AcpRuntime(name, config, event_bus=event_bus)

    if config.backend_type == "cli":
        from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import CliRuntime

        return CliRuntime(name, config)

    if config.backend_type == "sdk":
        from myrm_agent_harness.toolkits.acp.runtime.sdk_runtime import SdkRuntime

        return SdkRuntime(name, config)

    msg = f"Unknown backend_type: {config.backend_type!r}"
    raise ValueError(msg)


class RuntimePool:
    """Manages multiple RuntimeBackend instances with concurrency control.

    Usage::

        pool = RuntimePool(max_concurrent=4)
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        response = await pool.prompt("claude", "Fix the bug in main.py")
    """

    def __init__(
        self,
        *,
        max_concurrent: int = 4,
        event_bus: EventBus | None = None,
        enable_health_monitor: bool = False,
    ) -> None:
        self._configs: dict[str, RuntimeConfig] = {}
        self._backends: dict[str, RuntimeBackend] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._event_bus = event_bus
        self._health_monitor: HealthMonitor | None = (
            HealthMonitor(event_bus=event_bus) if enable_health_monitor else None
        )

    @property
    def available_backends(self) -> list[str]:
        """List all registered backend names."""
        return list(self._configs)

    def register(self, name: str, config: RuntimeConfig) -> None:
        """Register a backend configuration. Creates the backend lazily on first use."""
        self._configs[name] = config

    def get_config(self, name: str) -> RuntimeConfig | None:
        """Return the RuntimeConfig for a registered backend, or None if not found."""
        return self._configs.get(name)

    def get(self, name: str) -> RuntimeBackend:
        """Get or lazily create a RuntimeBackend by name.

        Raises:
            KeyError: If the name is not registered.
        """
        if name not in self._configs:
            available = ", ".join(self._configs) or "(none)"
            msg = f"Unknown backend '{name}'. Available: {available}"
            raise KeyError(msg)

        if name not in self._backends:
            backend = _create_runtime(name, self._configs[name], event_bus=self._event_bus)
            self._backends[name] = backend
            if self._health_monitor is not None:
                self._health_monitor.register(backend)

        return self._backends[name]

    async def prompt(self, name: str, task: str, *, mode: str = "persistent") -> str:
        """Send a task to the named backend with concurrency control.

        Collects all text_delta events and returns the concatenated response.
        """
        if mode == "oneshot":
            session_id = f"{name}-oneshot-{uuid4().hex}"
        elif mode == "persistent":
            session_id = f"{name}-default"
        else:
            msg = f"Invalid mode: {mode}"
            raise ValueError(msg)

        text_parts: list[str] = []
        async for event in self.run_turn(name, task, session_id=session_id, mode=mode):
            if event.type == RuntimeEventType.TEXT_DELTA:
                content = event.data.get("content")
                if isinstance(content, str):
                    text_parts.append(content)

        return "".join(text_parts)

    async def run_turn(
        self,
        name: str,
        prompt: str,
        session_id: str,
        *,
        mode: str = "persistent",
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream events from a backend turn with concurrency control.

        Use this instead of ``prompt()`` when you need the full event stream.
        """
        if mode not in {"persistent", "oneshot"}:
            msg = f"Invalid mode: {mode}"
            raise ValueError(msg)

        async with self._semaphore:
            backend = self.get(name)
            try:
                async for event in backend.run_turn(prompt, session_id):
                    if self._event_bus is not None:
                        await self._event_bus.emit(event)
                    yield event
            finally:
                if mode == "oneshot":
                    await backend.close()

    async def cancel(self, name: str, session_id: str) -> None:
        """Cancel a running turn for the named backend.

        Delegates to ``backend.cancel(session_id)`` which terminates the
        external process (e.g., SIGTERM → SIGKILL for CliRuntime).
        No-op if the backend hasn't been instantiated yet.
        """
        backend = self._backends.get(name)
        if backend is not None:
            await backend.cancel(session_id)
            logger.info("pool_cancel backend=%s session=%s", name, session_id)

    async def start_monitoring(self) -> None:
        """Start the health monitor if enabled. No-op if disabled."""
        if self._health_monitor is not None:
            await self._health_monitor.start()

    def get_health_metrics(self) -> dict[str, dict[str, object]]:
        """Return health metrics for all monitored backends."""
        if self._health_monitor is None:
            return {}
        return self._health_monitor.get_all_metrics()

    async def close_all(self) -> None:
        """Stop health monitoring and close all active backend connections."""
        if self._health_monitor is not None:
            await self._health_monitor.stop()

        async def _safe_close(name: str, backend: RuntimeBackend) -> None:
            try:
                await backend.close()
            except Exception:
                logger.warning("pool_close_failed backend=%s", name, exc_info=True)

        if self._backends:
            await asyncio.gather(*[_safe_close(n, b) for n, b in self._backends.items()])
        self._backends.clear()
        logger.info("runtime_pool_closed")
