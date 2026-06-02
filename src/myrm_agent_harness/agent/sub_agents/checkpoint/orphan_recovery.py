"""Orphan subagent checkpoint scanner.

Scans for interrupted checkpoint files on startup and publishes lifecycle
events so the business layer can notify the user via existing event bridges.
The user can then choose to resume or discard interrupted tasks from the UI.

[INPUT]
- .saver::SubagentCheckpointStorage (POS: Checkpoint persistence)
- utils.logger_utils::get_agent_logger (POS: Agent logging utility)
- runtime.events::get_event_bus (POS: Event publishing)
- runtime.events.system_events::SubagentLifecycleEvent, SubagentLifecycleData (POS: Lifecycle events)

[OUTPUT]
- OrphanRecoveryManager: Startup checkpoint scanner (singleton)

[POS]
Orphan subagent checkpoint scanner. Scans checkpoint directory on startup
and publishes lifecycle events so the UI can display interrupted tasks.
Does NOT attempt to resume or delete checkpoints — that is the business
layer's responsibility via the resume API.
"""

from __future__ import annotations

import asyncio
import time

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .saver import SubagentCheckpointStorage

logger = get_agent_logger(__name__)

_INITIAL_DELAY_SECONDS = 5.0

_instance: OrphanRecoveryManager | None = None


class OrphanRecoveryManager:
    """Scan for orphaned subagent checkpoints after restart and notify the UI.

    Lifecycle:
        1. Service startup calls ``get_instance().schedule_scan()``
        2. After initial delay, scans ``.myrm/checkpoints/`` for resumable files
        3. For each interrupted checkpoint: publish ``SubagentLifecycleEvent``
        4. ``harness_bridge`` receives event and rebuilds subagent tree
        5. Frontend displays interrupted tasks with resume button
    """

    __slots__ = ("_recovery_task", "_running", "_storage")

    def __init__(self, storage: SubagentCheckpointStorage | None = None) -> None:
        self._storage = storage or SubagentCheckpointStorage()
        self._running = False
        self._recovery_task: asyncio.Task[None] | None = None

    @classmethod
    def get_instance(
        cls, storage: SubagentCheckpointStorage | None = None,
    ) -> OrphanRecoveryManager:
        """Get or create the module-level singleton instance."""
        global _instance
        if _instance is None:
            _instance = cls(storage)
        return _instance

    def schedule_scan(
        self,
        delay_seconds: float = _INITIAL_DELAY_SECONDS,
    ) -> None:
        """Schedule orphan checkpoint scan after a delay.

        The delay gives the service time to fully bootstrap before scanning.

        Args:
            delay_seconds: Delay before first scan (default 5s)
        """
        if self._running:
            logger.debug("[orphan-recovery] Already scheduled, skipping")
            return
        self._running = True

        async def _run() -> None:
            await asyncio.sleep(delay_seconds)
            await self._scan_and_notify()
            self._running = False

        try:
            loop = asyncio.get_running_loop()
            self._recovery_task = loop.create_task(_run())
            logger.info(
                "[orphan-recovery] Scheduled scan in %.1fs", delay_seconds,
            )
        except RuntimeError:
            logger.warning("[orphan-recovery] No event loop available, skipping")
            self._running = False

    async def _scan_and_notify(self) -> None:
        """Scan checkpoint directory and publish events for interrupted checkpoints."""
        try:
            checkpoints = await self._storage.list_checkpoints()
        except Exception:
            logger.warning("[orphan-recovery] Failed to list checkpoints", exc_info=True)
            return

        if not checkpoints:
            return

        notified = 0
        for checkpoint in checkpoints:
            if not checkpoint.resumable:
                continue

            self._publish_event(
                checkpoint.task_id,
                checkpoint.agent_type,
                checkpoint.session_id,
                "orphan_detected",
                checkpoint.task_description,
            )
            notified += 1
            logger.info(
                "[orphan-recovery:%s] Detected interrupted checkpoint "
                "(agent_type=%s, progress=%.0f%%)",
                checkpoint.task_id, checkpoint.agent_type,
                checkpoint.progress * 100,
            )

        if notified > 0:
            logger.info(
                "[orphan-recovery] Scan complete: %d interrupted checkpoint(s) found",
                notified,
            )

    @staticmethod
    def _publish_event(
        task_id: str,
        agent_type: str,
        session_id: str,
        event_name: str,
        task_description: str = "",
    ) -> None:
        """Publish a SubagentLifecycleEvent for checkpoint discovery."""
        try:
            from myrm_agent_harness.runtime.events import get_event_bus
            from myrm_agent_harness.runtime.events.system_events import (
                SubagentLifecycleData,
                SubagentLifecycleEvent,
            )

            event = SubagentLifecycleEvent(
                event_name=event_name,
                task_id=task_id,
                session_id=session_id,
                data=SubagentLifecycleData(
                    agent_type=agent_type,
                    description=task_description,
                    status="interrupted",
                ),
                created_at=time.time(),
            )
            get_event_bus().publish(event)
        except Exception:
            logger.debug(
                "[orphan-recovery:%s] Failed to publish %s event",
                task_id, event_name, exc_info=True,
            )
