"""OptimizationScheduler monitoring and evaluation APIs.

[INPUT]
- .protocols.SkillExecutionProvider (POS: execution event provider)
- .quality_calculator.QualityCalculator (POS: quality score calculator)
- .types.SkillQualityScore (POS: optimization quality types)

[OUTPUT]
- OptimizationSchedulerMonitoringMixin: monitoring loop, skill evaluation, trigger_optimization

[POS]
Periodic skill quality monitoring and optimization trigger for OptimizationScheduler.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata

    from .types import SkillQualityScore

logger = logging.getLogger(__name__)


class OptimizationSchedulerMonitoringMixin:
    async def start_monitoring(self) -> None:
        """启动实时监控

        定时评估所有skill质量，触发优化。
        同时启动queue worker处理优化队列。
        """
        if self._monitoring_task and not self._monitoring_task.done():
            logger.warning("Monitoring task already running")
            return

        logger.info("Starting skill optimization monitoring")
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())

        await self.start_queue_worker()

    async def stop_monitoring(self) -> None:
        """停止监控和队列worker"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitoring_task
            logger.info("Skill optimization monitoring stopped")

        await self.stop_queue_worker()

    async def _monitoring_loop(self) -> None:
        """监控循环（定时评估）"""
        while True:
            try:
                await asyncio.sleep(self.config.monitoring.evaluation_interval)
                await self._evaluate_all_skills()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")

    async def _evaluate_all_skills(self) -> None:
        """评估所有skill并触发优化"""
        logger.info("Evaluating all skills for optimization opportunities")

        try:
            skill_ids = await self.execution_provider.get_all_skill_ids()
            logger.info(f"Found {len(skill_ids)} skills to evaluate")

            for skill_id in skill_ids:
                try:
                    await self._evaluate_skill(skill_id)
                except Exception as e:
                    logger.error(f"Failed to evaluate skill {skill_id}: {e}")

            if self.anomaly_detector:
                try:
                    await self._detect_and_handle_anomalies()
                except Exception as e:
                    logger.error(f"Anomaly detection failed: {e}")

        except Exception as e:
            logger.error(f"Failed to get skill IDs: {e}")

    async def _detect_and_handle_anomalies(self) -> None:
        """检测异常并自动触发优化"""
        if not self.anomaly_detector:
            return

        try:
            anomalies = await self.anomaly_detector.detect_quality_anomalies(days=7, sigma_threshold=3.0)

            if not anomalies:
                logger.debug("No quality anomalies detected")
                return

            logger.warning(f"Detected {len(anomalies)} quality anomalies")

            for anomaly in anomalies:
                logger.warning(
                    f"Anomaly detected in skill {anomaly.skill_id}: "
                    f"z_score={anomaly.z_score:.2f}, root_cause={anomaly.root_cause.cause_type}"
                )

                await self.event_emitter.emit(
                    "anomaly_detected",
                    {
                        "skill_id": anomaly.skill_id,
                        "timestamp": anomaly.timestamp.isoformat(),
                        "quality_score": anomaly.quality_score,
                        "z_score": anomaly.z_score,
                        "root_cause": anomaly.root_cause.cause_type,
                    },
                )

                await self._evaluate_skill(anomaly.skill_id)

        except Exception as e:
            logger.error(f"Failed to detect anomalies: {e}")

    async def _evaluate_skill(self, skill_id: str) -> None:
        """评估单个skill"""
        samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=7)

        if not samples:
            logger.debug(f"No execution samples for skill: {skill_id}")
            return

        quality_score = await self.quality_calculator.calculate(samples, skill_id=skill_id)

        if quality_score.overall_score < self.config.monitoring.optimization_threshold:
            logger.info(
                f"Skill {skill_id} quality below threshold: "
                f"{quality_score.overall_score:.2f} < {self.config.monitoring.optimization_threshold}"
            )

            skill_metadata = await self.execution_provider.get_skill_metadata(skill_id)
            if skill_metadata:
                content = await self.execution_provider.get_skill_content(skill_id)
                await self.trigger_optimization(skill_metadata, quality_score, content=content)
            else:
                logger.warning(f"Skill metadata not found for {skill_id}, skipping optimization")

    async def trigger_optimization(
        self,
        skill: SkillMetadata,
        quality_score: SkillQualityScore,
        use_queue: bool = True,
        content: str | None = None,
    ) -> bool:
        """触发skill优化"""
        if quality_score.overall_score >= self.config.monitoring.optimization_threshold:
            logger.debug(f"Skill quality above threshold: {skill.name}")
            return False

        if not self._check_cooldown(skill.name):
            logger.debug(f"Skill in cooldown period: {skill.name}")
            return False

        if self._is_circuit_broken(skill.name):
            logger.warning(f"Circuit breaker tripped for skill: {skill.name}")
            return False

        if use_queue:
            await self._optimization_queue.put((skill, quality_score, content))
            logger.info(f"Skill optimization queued: {skill.name}")

            await self.event_emitter.emit(
                "optimization_queued",
                {
                    "skill_id": skill.name,
                    "quality_score": quality_score.overall_score,
                    "queue_size": self._optimization_queue.qsize(),
                },
            )

            return True

        try:
            await self._execute_optimization(skill, quality_score, content=content)
            logger.info(f"Skill optimization triggered (direct): {skill.name}")
            return True

        except Exception as e:
            logger.error(f"Skill optimization failed: {skill.name}, error: {e}")
            return False
