"""Compatibility adapter that delegates cognitive consolidation to the unified core.

[INPUT]
- infra.cooperative_signals::CooperativePauseSignal (POS: Infrastructure layer. Provides transaction-boundary cooperative yielding so background consolidation immediately yields SQLite write locks when foreground users type.)
- toolkits.memory.manager::MemoryManager (POS: Stable public import path for the memory toolkit façade.)

[OUTPUT]
- ConsolidationResult: Maintenance report mapped into the legacy consolidation shape, with a ``to_dict`` projection
- CognitiveConsolidator: Adapter that drives ``MemoryManager.run_maintenance_cycle()`` and owns no consolidation logic of its own

[POS]
Memory toolkit's cognitive consolidation adapter. Forwards consolidation, forgetting, and
health checks to the single maintenance core so the system keeps exactly one maintenance path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from myrm_agent_harness.infra.cooperative_signals import (
    CooperativePauseSignal,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """Compatibility result mapped from the unified maintenance report."""

    profiles_updated: int = 0
    semantics_created: int = 0
    memories_merged: int = 0
    noise_removed: int = 0
    candidates_processed: int = 0
    corrected: int = 0
    updated: int = 0
    archived: int = 0
    duration_ms: float = 0.0
    skipped: bool = False
    skip_reason: str = ""
    interrupted_by_pause: bool = False
    insights: tuple[str, ...] = ()
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "profiles_updated": self.profiles_updated,
            "semantics_created": self.semantics_created,
            "memories_merged": self.memories_merged,
            "noise_removed": self.noise_removed,
            "candidates_processed": self.candidates_processed,
            "corrected": self.corrected,
            "updated": self.updated,
            "archived": self.archived,
            "duration_ms": self.duration_ms,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "interrupted_by_pause": self.interrupted_by_pause,
            "insights": list(self.insights),
            "errors": self.errors,
            "success": not self.errors and not self.skipped,
        }


class CognitiveConsolidator:
    """Compatibility adapter that delegates to the single maintenance core."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        consolidation_interval: float = 3600.0,
        min_candidates: int = 0,
        max_batch_size: int = 0,
    ) -> None:
        self.memory_manager = memory_manager
        self.consolidation_interval = consolidation_interval
        self.min_candidates = min_candidates
        self.max_batch_size = max_batch_size
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._consolidation_count = 0

    async def start(self) -> None:
        """Start the compatibility loop that triggers the unified maintenance cycle."""
        if self._running:
            logger.warning("CognitiveConsolidator already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._consolidation_loop())
        logger.info(
            "CognitiveConsolidator started as maintenance-core adapter (interval=%ss)", self.consolidation_interval
        )

    async def stop(self) -> None:
        """Stop the compatibility loop."""
        self._running = False
        if self._task is None:
            logger.info("CognitiveConsolidator stopped")
            return

        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("CognitiveConsolidator stopped")

    async def _consolidation_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.consolidation_interval)
                result = await self.run_consolidation()
                self._consolidation_count += 1
                logger.info(
                    "[Maintenance Adapter #%d] merged=%d corrected=%d updated=%d forgotten=%d archived=%d skipped=%s",
                    self._consolidation_count,
                    result.memories_merged,
                    result.corrected,
                    result.updated,
                    result.noise_removed,
                    result.archived,
                    result.skipped,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("CognitiveConsolidator loop error: %s", exc, exc_info=True)

    async def run_consolidation(self, *, pause_signal: CooperativePauseSignal | None = None) -> ConsolidationResult:
        """Delegate to the unified maintenance cycle and map its report."""
        if pause_signal is not None:
            report = await self.memory_manager.run_maintenance_cycle(force=True, pause_signal=pause_signal)
        else:
            report = await self.memory_manager.run_maintenance_cycle(force=True)
        errors: list[str] = []
        if (
            report.skipped
            and report.skip_reason
            and not report.interrupted_by_pause
            and report.skip_reason != "already running"
        ):
            errors.append(f"maintenance skipped: {report.skip_reason}")
        if report.consolidation_errors:
            errors.append(f"maintenance consolidation errors: {report.consolidation_errors}")

        return ConsolidationResult(
            memories_merged=report.consolidation_merged,
            noise_removed=report.forgotten_count,
            candidates_processed=(
                report.consolidation_merged + report.consolidation_corrected + report.consolidation_updated
            ),
            corrected=report.consolidation_corrected,
            updated=report.consolidation_updated,
            archived=report.archived_count,
            duration_ms=report.duration_ms,
            skipped=report.skipped,
            skip_reason=report.skip_reason,
            interrupted_by_pause=report.interrupted_by_pause,
            insights=report.insights,
            errors=errors,
        )
