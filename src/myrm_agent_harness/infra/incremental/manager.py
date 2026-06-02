"""Incremental monitor lifecycle manager.

Manages monitor instances, TTL expiration, and storage coordination.

[INPUT]
- toolkits.cron.protocols::CronStore (POS: Protocols for the cron toolkit.)

[OUTPUT]
- IncrementalMonitorManager: Manages incremental monitor instances with TTL and storage.

[POS]
Incremental monitor lifecycle manager.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.infra.incremental.set_monitor import SetMonitor
from myrm_agent_harness.infra.incremental.types import MonitorConfig, MonitorState

if TYPE_CHECKING:
    from myrm_agent_harness.infra.incremental.protocols import IncrementalMonitor
    from myrm_agent_harness.toolkits.cron.protocols import CronStore

logger = logging.getLogger(__name__)


class IncrementalMonitorManager:
    """Manages incremental monitor instances with TTL and storage.

    Responsibilities:
    1. Create/restore monitor instances from storage
    2. Handle TTL expiration (auto-reset baseline after ttl_days)
    3. Coordinate monitor state persistence
    4. Provide unified API for cron executor

    Design:
    - Single-responsibility: only manages monitors, doesn't execute jobs
    - Storage-agnostic: delegates persistence to CronStore
    - Type-safe: no Any types, all monitors implement Protocol
    """

    def __init__(self, store: CronStore) -> None:
        """Initialize manager with storage backend.

        Args:
            store: CronStore implementation for persisting monitor state.
        """
        self._store = store
        self._cache: dict[str, IncrementalMonitor] = {}

    async def get_monitor(
        self,
        job_id: str,
        config: MonitorConfig,
    ) -> tuple[IncrementalMonitor, str | None]:
        """Get or create monitor instance for a job.

        Args:
            job_id: Unique job identifier.
            config: Monitor configuration (type, TTL, etc.).

        Returns:
            Tuple of (monitor instance, reset_reason).
            reset_reason is None if monitor from cache, "first_run" for new monitors,
            or "ttl_expired" if baseline was reset due to TTL expiration.

        Raises:
            ValueError: If monitor_type is not supported.
        """
        if job_id in self._cache:
            return self._cache[job_id], None

        state = await self._store.get_monitor_state(job_id)
        reset_reason: str | None = None

        if state and state.is_expired():
            logger.info(
                "Monitor state for job %s expired (age: %d days, TTL: %d days) — resetting baseline",
                job_id,
                (datetime.now(UTC) - state.updated_at).days,
                state.ttl_days,
            )
            reset_reason = "ttl_expired"
            state = None
        elif state is None:
            reset_reason = "first_run"

        monitor = self._create_monitor(config, state)
        self._cache[job_id] = monitor
        return monitor, reset_reason

    async def save_monitor_state(
        self,
        job_id: str,
        monitor: IncrementalMonitor,
        config: MonitorConfig,
    ) -> None:
        """Persist monitor state to storage after successful monitoring.

        Args:
            job_id: Unique job identifier.
            monitor: Monitor instance to persist.
            config: Monitor configuration.

        Note:
            This method resets failure_count to 0 on successful save.
        """
        if not isinstance(monitor, SetMonitor):
            logger.warning(
                "save_monitor_state: unsupported monitor type %s",
                type(monitor).__name__,
            )
            return

        state = MonitorState(
            job_id=job_id,
            monitor_type=config.monitor_type,
            data=monitor.get_state_data(),
            updated_at=datetime.now(UTC),
            ttl_days=config.ttl_days,
            failure_count=0,
            last_failure_at=None,
        )

        await self._store.save_monitor_state(state)

    async def record_monitor_failure(
        self,
        job_id: str,
        config: MonitorConfig,
        error: Exception,
    ) -> int:
        """Record a monitoring failure and return consecutive failure count.

        Args:
            job_id: Unique job identifier.
            config: Monitor configuration.
            error: Exception that caused the failure.

        Returns:
            Consecutive failure count after recording this failure.
        """
        state = await self._store.get_monitor_state(job_id)

        failure_count = (state.failure_count + 1) if state else 1
        now = datetime.now(UTC)

        updated_state = MonitorState(
            job_id=job_id,
            monitor_type=config.monitor_type,
            data=state.data if state else {},
            updated_at=state.updated_at if state else now,
            ttl_days=config.ttl_days,
            failure_count=failure_count,
            last_failure_at=now,
        )

        await self._store.save_monitor_state(updated_state)

        return failure_count

    def _create_monitor(
        self,
        config: MonitorConfig,
        state: MonitorState | None,
    ) -> IncrementalMonitor:
        """Create monitor instance from config and optional state.

        Args:
            config: Monitor configuration.
            state: Optional persisted state (None for first run).

        Returns:
            Monitor instance.

        Raises:
            ValueError: If monitor_type is not supported.
        """
        if config.monitor_type == "set":
            if state:
                return SetMonitor.from_state_data(state.data, config.ttl_days)
            return SetMonitor(seen=None, ttl_days=config.ttl_days)

        raise ValueError(f"Unsupported monitor type: {config.monitor_type}")

    def clear_cache(self, job_id: str | None = None) -> None:
        """Clear cached monitor instances.

        Args:
            job_id: If provided, clear only this job's monitor.
                   If None, clear all cached monitors.
        """
        if job_id:
            self._cache.pop(job_id, None)
        else:
            self._cache.clear()
