"""OptimizationScheduler batch optimization APIs.

[INPUT]
- .optimizer.SkillOptimizer (POS: skill optimization engine)
- .event_emitter.EventEmitter (POS: publish-subscribe event bus)

[OUTPUT]
- OptimizationSchedulerBatchMixin: batch trigger, cancel, status, parallel execution

[POS]
Batch skill optimization orchestration for OptimizationScheduler.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class OptimizationSchedulerBatchMixin:
    def _is_batch_cancelled(self, batch_task_id: str) -> bool:
        token = self._batch_cancel_tokens.get(batch_task_id)
        return token is not None and token.is_set()

    async def cancel_batch_optimization(self, batch_task_id: str) -> bool:
        """Request cancellation of a running batch optimization."""
        if batch_task_id not in self._batch_tasks:
            return False

        token = self._batch_cancel_tokens.get(batch_task_id)
        if token is None:
            return False

        token.set()
        self._batch_tasks[batch_task_id]["status"] = "cancelled"
        logger.info("Batch optimization cancellation requested: %s", batch_task_id)
        return True

    async def await_batch_optimization(self, batch_task_id: str, timeout: float = 120.0) -> bool:
        """Wait for batch background execution to finish."""
        task = self._batch_bg_tasks.get(batch_task_id)
        if task is None:
            return True

        try:
            await asyncio.wait_for(task, timeout=timeout)
        except TimeoutError:
            logger.warning(
                "Batch %s did not finish within %.0fs after cancel",
                batch_task_id,
                timeout,
            )
            return False
        return True

    async def trigger_batch_optimization(
        self,
        skill_ids: list[str],
        max_concurrent: int = 3,
        priority: int = 0,
        batch_task_id: str | None = None,
    ) -> str:
        """批量触发skill优化（F1）"""
        batch_task_id = batch_task_id or f"batch_{uuid.uuid4().hex[:8]}"

        self._batch_tasks[batch_task_id] = {
            "total": len(skill_ids),
            "completed": 0,
            "failed": 0,
            "status": "running",
            "started_at": datetime.now(),
            "skill_ids": skill_ids,
            "priority": priority,
        }
        self._batch_cancel_tokens[batch_task_id] = asyncio.Event()

        logger.info(
            f"Batch optimization started: {batch_task_id}, {len(skill_ids)} skills, "
            f"max_concurrent={max_concurrent}, priority={priority}"
        )

        batch_task = asyncio.create_task(self._execute_batch_optimization(batch_task_id, skill_ids, max_concurrent))
        self._batch_bg_tasks[batch_task_id] = batch_task
        self._bg_tasks.add(batch_task)

        def _on_batch_done(done_task: asyncio.Task[None]) -> None:
            self._bg_tasks.discard(done_task)
            self._batch_bg_tasks.pop(batch_task_id, None)

        batch_task.add_done_callback(_on_batch_done)

        return batch_task_id

    async def _execute_batch_optimization(self, batch_task_id: str, skill_ids: list[str], max_concurrent: int) -> None:
        """执行批量优化（内部方法）"""
        try:
            semaphore = asyncio.Semaphore(max_concurrent)

            async def optimize_one(skill_id: str) -> bool:
                async with semaphore:
                    if self._is_batch_cancelled(batch_task_id):
                        logger.info(
                            "Batch %s cancelled, skipping skill %s",
                            batch_task_id,
                            skill_id,
                        )
                        return False

                    try:
                        samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=7)

                        if not samples:
                            logger.warning(f"No execution samples for skill: {skill_id}")
                            return False

                        quality_score = await self.quality_calculator.calculate(samples, skill_id=skill_id)

                        if quality_score.overall_score < self.config.monitoring.optimization_threshold:
                            skill_metadata = await self.execution_provider.get_skill_metadata(skill_id)
                            if skill_metadata:
                                if self._is_batch_cancelled(batch_task_id):
                                    return False

                                content = await self.execution_provider.get_skill_content(skill_id)
                                await self.optimizer.optimize_skill(skill_metadata, quality_score, content=content)

                                if self._is_batch_cancelled(batch_task_id):
                                    logger.info(
                                        "Batch %s cancelled, discarding optimization result for %s",
                                        batch_task_id,
                                        skill_id,
                                    )
                                    return False

                                logger.info(f"Batch optimization completed for skill: {skill_id}")
                            else:
                                logger.warning(f"Skill metadata not found: {skill_id}")
                                return False
                        else:
                            logger.info(
                                f"Skill quality above threshold, skipping: {skill_id} "
                                f"(score: {quality_score.overall_score})"
                            )

                        return True

                    except Exception as e:
                        logger.error(f"Batch optimization error for {skill_id}: {e}")
                        return False

            total = len(skill_ids)
            completed = 0
            failed = 0

            tasks = [asyncio.create_task(optimize_one(skill_id)) for skill_id in skill_ids]

            for task in asyncio.as_completed(tasks):
                try:
                    result = await task
                    if result:
                        completed += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

                progress_percent = (completed + failed) / total
                await self.event_emitter.emit(
                    "batch_optimization_progress",
                    {
                        "batch_task_id": batch_task_id,
                        "total": total,
                        "completed": completed,
                        "failed": failed,
                        "progress_percent": progress_percent,
                    },
                )

            final_status = "cancelled" if self._is_batch_cancelled(batch_task_id) else "completed"
            self._batch_tasks[batch_task_id].update(
                {
                    "completed": completed,
                    "failed": failed,
                    "status": final_status,
                    "completed_at": datetime.now(),
                }
            )

            logger.info(
                "Batch optimization finished: %s, status=%s, succeeded=%s, failed=%s",
                batch_task_id,
                final_status,
                completed,
                failed,
            )

            await self.event_emitter.emit(
                "batch_optimization_completed",
                {
                    "batch_task_id": batch_task_id,
                    "total": len(skill_ids),
                    "succeeded": completed,
                    "failed": failed,
                    "status": final_status,
                },
            )
        finally:
            self._batch_cancel_tokens.pop(batch_task_id, None)

    def get_batch_status(self, batch_task_id: str) -> dict[str, Any] | None:
        """获取批量任务状态（F6）"""
        return self._batch_tasks.get(batch_task_id)
