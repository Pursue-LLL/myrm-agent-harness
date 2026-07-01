"""OptimizationScheduler queue worker and execution APIs.

[INPUT]
- .optimizer.SkillOptimizer (POS: skill optimization engine)
- .event_emitter.EventEmitter (POS: publish-subscribe event bus)

[OUTPUT]
- OptimizationSchedulerQueueMixin: queue worker lifecycle and _execute_optimization

[POS]
Async optimization queue processing for OptimizationScheduler.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata

    from .types import SkillQualityScore

logger = logging.getLogger(__name__)


class OptimizationSchedulerQueueMixin:
    async def start_queue_worker(self) -> None:
        """启动队列worker（F2）"""
        if self._queue_worker_task and not self._queue_worker_task.done():
            logger.warning("Queue worker already running")
            return

        logger.info("Starting optimization queue worker")
        self._queue_worker_task = asyncio.create_task(self._queue_worker())

    async def stop_queue_worker(self) -> None:
        """停止队列worker"""
        if self._queue_worker_task:
            self._queue_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_worker_task
            logger.info("Optimization queue worker stopped")

    async def _queue_worker(self) -> None:
        """队列worker循环（F2）"""
        while True:
            try:
                queue_item = await self._optimization_queue.get()

                if len(queue_item) == 2:
                    skill, quality_score = queue_item
                    content = None
                else:
                    skill, quality_score, content = queue_item

                logger.info(f"Queue worker processing: {skill.name}")

                try:
                    await self._execute_optimization(skill, quality_score, content=content)
                except Exception as e:
                    logger.error(f"Queue worker error for {skill.name}: {e}")
                finally:
                    self._optimization_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue worker loop error: {e}")

    async def _execute_optimization(
        self,
        skill: SkillMetadata,
        quality_score: SkillQualityScore,
        content: str | None = None,
    ) -> None:
        """执行优化（内部方法）"""
        from . import prometheus_metrics as prom

        prom.record_optimization_start(skill.name)
        start_time = time.time()

        self._metrics["optimization_total"] += 1

        try:
            result = await self.optimizer.optimize_skill(skill, quality_score, content=content)
            duration = time.time() - start_time

            self._record_success(skill.name)
            self._metrics["optimization_success"] += 1

            prom.record_optimization_success(skill.name, result.version, duration)

            if quality_score.llm_cost_usd > 0:
                prom.record_llm_cost(skill.name, "unknown", quality_score.llm_cost_usd)
            if quality_score.total_tokens > 0:
                prom.record_llm_tokens(
                    skill.name, "unknown", quality_score.prompt_tokens, quality_score.completion_tokens
                )

            await self.event_emitter.emit(
                "optimization_completed",
                {
                    "skill_id": skill.name,
                    "quality_score": quality_score.overall_score,
                    "status": "success",
                    "result": {
                        "version": result.version,
                        "baseline_score": result.baseline_score.overall_score,
                    },
                },
            )

            logger.info(f"Skill optimization completed: {skill.name}")

        except Exception as e:
            duration = time.time() - start_time
            error_message = str(e)

            self._record_failure(skill.name, error_message)
            self._metrics["optimization_failed"] += 1

            prom.record_optimization_failure(skill.name, "execution_error", duration)

            await self.event_emitter.emit(
                "optimization_completed",
                {
                    "skill_id": skill.name,
                    "quality_score": quality_score.overall_score,
                    "status": "failed",
                    "error": str(e),
                },
            )

            logger.error(f"Skill optimization failed: {skill.name}, error: {e}")
            raise
