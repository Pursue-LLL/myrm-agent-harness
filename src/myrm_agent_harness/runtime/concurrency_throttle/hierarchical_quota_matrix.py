"""Multi-tier hierarchical quota matrix and semaphore isolation engine.

Enforces strict physical separation between Gateway Ingress, Agent Instances,
LLM Calls, Network I/O Tools, and Heavy Sandbox CPU Processes to eliminate fan-out collapse.

[INPUT]
- __future__
- asyncio
- time
- uuid
- collections
- contextlib

[OUTPUT]
- HierarchicalQuotaMatrix

[POS]
Multi-tier hierarchical quota matrix and semaphore isolation engine.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .throttle_types import (
    ResourceLeaseTicket,
    ResourceTier,
    TierQuotaConfig,
)


class HierarchicalQuotaMatrix:
    """Manages independent semaphore pools across architectural tiers to prevent resource starvation."""

    def __init__(self, configs: list[TierQuotaConfig] | None = None) -> None:
        self._configs: dict[ResourceTier, TierQuotaConfig] = {}
        self._semaphores: dict[ResourceTier, asyncio.Semaphore] = {}
        self._active_leases: dict[ResourceTier, int] = {}
        self._initialize_defaults(configs)

    def _initialize_defaults(self, custom_configs: list[TierQuotaConfig] | None) -> None:
        """Initialize default quota capacities for all tiers."""
        default_configs = [
            TierQuotaConfig(ResourceTier.GATEWAY_INGRESS, max_concurrency=100),
            TierQuotaConfig(ResourceTier.AGENT_INSTANCE, max_concurrency=20),
            TierQuotaConfig(ResourceTier.LLM_PROVIDER, max_concurrency=30),
            TierQuotaConfig(ResourceTier.TOOL_IO, max_concurrency=40),
            TierQuotaConfig(ResourceTier.TOOL_SANDBOX_CPU, max_concurrency=4),
        ]

        active_map: dict[ResourceTier, TierQuotaConfig] = {c.tier: c for c in default_configs}
        if custom_configs:
            for c in custom_configs:
                active_map[c.tier] = c

        for tier, config in active_map.items():
            self._configs[tier] = config
            self._semaphores[tier] = asyncio.Semaphore(config.max_concurrency)
            self._active_leases[tier] = 0

    @asynccontextmanager
    async def acquire_lease(
        self,
        tier: ResourceTier,
        session_id: str = "global",
        timeout_s: float | None = None,
    ) -> AsyncIterator[ResourceLeaseTicket]:
        """Asynchronously acquire a lease ticket for a specific resource tier.

        Guarantees strictly leak-free release via async context management.
        """
        sem = self._semaphores.get(tier)
        if sem is None:
            raise KeyError(f"Resource tier '{tier}' is not configured in quota matrix.")

        # Acquire semaphore with optional timeout protection
        if timeout_s is not None:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=timeout_s)
            except TimeoutError as err:
                raise TimeoutError(
                    f"Timed out after {timeout_s}s waiting for lease on tier '{tier.value}'."
                ) from err
        else:
            await sem.acquire()

        ticket = ResourceLeaseTicket(
            lease_id=f"lease_{uuid.uuid4().hex[:8]}",
            tier=tier,
            session_id=session_id,
            acquired_at=time.time(),
        )
        self._active_leases[tier] = self._active_leases.get(tier, 0) + 1

        try:
            yield ticket
        finally:
            # Absolute invariant: release semaphore and decrement counters in all exit conditions
            sem.release()
            self._active_leases[tier] = max(0, self._active_leases.get(tier, 1) - 1)

    def get_tier_utilization(self, tier: ResourceTier) -> float:
        """Return the current utilization ratio (0.0 to 1.0) of a given resource tier."""
        cfg = self._configs.get(tier)
        if cfg is None or cfg.max_concurrency <= 0:
            return 0.0
        active = self._active_leases.get(tier, 0)
        return min(1.0, active / cfg.max_concurrency)

    def is_high_watermark(self, tier: ResourceTier) -> bool:
        """Check if a tier has crossed its configured backpressure high-watermark threshold."""
        cfg = self._configs.get(tier)
        if cfg is None:
            return False
        return self.get_tier_utilization(tier) >= cfg.high_watermark_ratio

    def get_active_leases_snapshot(self) -> dict[str, int]:
        """Return a read-only snapshot dictionary of currently active leases per tier."""
        return {tier.value: count for tier, count in self._active_leases.items()}
