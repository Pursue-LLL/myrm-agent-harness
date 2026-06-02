"""@input: MemoryManager
@output: 认知整合Result（compatible壳）
@pos: 记忆系统 / 认知整合层

compatible层： not 再维护第二套independent认知整合implements。

自现 in 起，AllBackground整合、遗忘、健康Check都统一委托给
`MemoryManager.run_maintenance_cycle()`， guarantee 系统只 has 一条维护主链。

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: Unified memory manager and core facade of the Memory Toolkit. Orchestrates all memory operations via pure dependency injection — no concrete backends, only protocols.)

[OUTPUT]
- ConsolidationResult: Compatibility result mapped from the unified maintenance ...
- CognitiveConsolidator: Compatibility adapter that delegates to the single mainte...

[POS]
@input: MemoryManager
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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

    async def run_consolidation(self) -> ConsolidationResult:
        """Delegate to the unified maintenance cycle and map its report."""
        report = await self.memory_manager.run_maintenance_cycle(force=True)
        errors: list[str] = []
        if report.skipped and report.skip_reason:
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
            insights=report.insights,
            errors=errors,
        )
