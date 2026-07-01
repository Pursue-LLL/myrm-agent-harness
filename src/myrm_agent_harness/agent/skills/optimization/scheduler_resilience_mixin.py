"""OptimizationScheduler resilience, hooks, metrics, and DLQ APIs.

[INPUT]
- .dlq.DeadLetterQueue (POS: dead letter queue with persistence)
- agent.hooks.HookRegistry (POS: hook registration)
- .config.OptimizationConfig (POS: optimization configuration)

[OUTPUT]
- OptimizationSchedulerResilienceMixin: cooldown, circuit breaker, DLQ, metrics, health

[POS]
Resilience and observability helpers for OptimizationScheduler.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import OptimizationConfig

logger = logging.getLogger(__name__)


class OptimizationSchedulerResilienceMixin:
    def _check_cooldown(self, skill_id: str) -> bool:
        """检查冷却期"""
        last_opt_time = self._cooldown_tracker.get(skill_id)
        if not last_opt_time:
            return True

        cooldown_period = timedelta(seconds=self.config.monitoring.cooldown_period)
        return datetime.now() - last_opt_time > cooldown_period

    def _is_circuit_broken(self, skill_id: str) -> bool:
        """检查断路器状态"""
        failures = self._circuit_breaker.get(skill_id, 0)
        return failures >= self.config.monitoring.circuit_breaker_threshold

    def _record_success(self, skill_id: str) -> None:
        """记录优化成功"""
        self._cooldown_tracker[skill_id] = datetime.now()
        self._circuit_breaker[skill_id] = 0

    def _record_failure(self, skill_id: str, error_message: str | None = None) -> None:
        """记录优化失败"""
        self._circuit_breaker[skill_id] += 1

        if self._is_circuit_broken(skill_id):
            self._dead_letter_queue.append(
                {
                    "skill_id": skill_id,
                    "attempts": self._circuit_breaker[skill_id],
                    "last_error": error_message or "Unknown error",
                    "timestamp": datetime.now().isoformat(),
                    "task_id": f"dlq-{skill_id}-{uuid.uuid4().hex[:8]}",
                }
            )
            logger.warning(f"Skill moved to DLQ after {self._circuit_breaker[skill_id]} failures: {skill_id}")

    def _register_hooks(self, hook_registry) -> None:  # type: ignore[no-untyped-def]
        """注册Hook System钩子"""
        from myrm_agent_harness.agent.hooks import CallableHookDefinition, HookEvent, HookResult

        async def _on_post_tool_use(event_name: str, payload: dict) -> HookResult:  # type: ignore[type-arg]
            try:
                tool_name = payload.get("tool_name", "")

                if tool_name.startswith("skill_"):
                    skill_id = tool_name[6:]
                    logger.debug(f"Skill executed via Hook: {skill_id}")

            except Exception as e:
                logger.error(f"Hook callback error: {e}")

            return HookResult(hook_type="callable", success=True, output="Skill execution tracked")

        hook_def = CallableHookDefinition(type="callable", fn=_on_post_tool_use, matcher="skill_*")

        hook_registry.register(HookEvent.POST_TOOL_USE, hook_def)
        logger.info("Registered POST_TOOL_USE Hook for skill optimization monitoring")

    async def health_check(self) -> dict[str, bool | str | int]:
        """健康检查"""
        try:
            monitoring_active = self._monitoring_task is not None and not self._monitoring_task.done()
            queue_worker_active = self._queue_worker_task is not None and not self._queue_worker_task.done()

            return {
                "healthy": True,
                "component": "optimization_scheduler",
                "monitoring_active": monitoring_active,
                "queue_worker_active": queue_worker_active,
                "queue_size": self._optimization_queue.qsize(),
                "cooldown_count": len(self._cooldown_tracker),
                "circuit_breaker_count": len(self._circuit_breaker),
                "batch_tasks_count": len(self._batch_tasks),
            }
        except Exception as e:
            return {
                "healthy": False,
                "component": "optimization_scheduler",
                "error": str(e),
            }

    async def reload_config(self, new_config: OptimizationConfig) -> None:
        """热加载配置（F9）"""
        old_config = self.config
        self.config = new_config

        logger.info(
            "Config reloaded",
            extra={
                "old_optimization_threshold": old_config.monitoring.optimization_threshold,
                "new_optimization_threshold": new_config.monitoring.optimization_threshold,
                "old_cooldown_period": old_config.monitoring.cooldown_period,
                "new_cooldown_period": new_config.monitoring.cooldown_period,
            },
        )

        await self.event_emitter.emit(
            "config_reloaded",
            {
                "old_config": {
                    "optimization_threshold": old_config.monitoring.optimization_threshold,
                    "cooldown_period": old_config.monitoring.cooldown_period,
                    "circuit_breaker_threshold": old_config.monitoring.circuit_breaker_threshold,
                },
                "new_config": {
                    "optimization_threshold": new_config.monitoring.optimization_threshold,
                    "cooldown_period": new_config.monitoring.cooldown_period,
                    "circuit_breaker_threshold": new_config.monitoring.circuit_breaker_threshold,
                },
            },
        )

    def get_metrics(self) -> dict[str, int | float]:
        """获取Prometheus格式指标（F8）"""
        circuit_breaker_tripped = sum(
            1
            for failures in self._circuit_breaker.values()
            if failures >= self.config.monitoring.circuit_breaker_threshold
        )

        queue_size = self._optimization_queue.qsize()
        dlq_size = len(self._dead_letter_queue)

        from . import prometheus_metrics as prom

        prom.update_queue_size(queue_size)
        prom.update_circuit_breaker_count(circuit_breaker_tripped)
        prom.update_dlq_size(dlq_size)

        return {
            "optimization_total": self._metrics["optimization_total"],
            "optimization_success": self._metrics["optimization_success"],
            "optimization_failed": self._metrics["optimization_failed"],
            "optimization_success_rate": (
                self._metrics["optimization_success"] / self._metrics["optimization_total"]
                if self._metrics["optimization_total"] > 0
                else 0.0
            ),
            "queue_size": queue_size,
            "cooldown_count": len(self._cooldown_tracker),
            "circuit_breaker_tripped": circuit_breaker_tripped,
            "batch_tasks_count": len(self._batch_tasks),
            "dlq_size": dlq_size,
        }

    def get_dlq_tasks(self) -> list[dict[str, Any]]:
        """获取死信队列中的所有任务"""
        return self._dead_letter_queue.get_all()

    async def retry_dlq_task(self, task_id: str) -> bool:
        """手动重试DLQ中的任务"""
        task = self._dead_letter_queue.find_by_id(task_id)

        if not task:
            logger.warning(f"DLQ task not found: {task_id}")
            return False

        skill_id = task["skill_id"]

        self._circuit_breaker[skill_id] = 0

        self._dead_letter_queue.remove(task)

        try:
            samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=7)
            if not samples:
                logger.warning(f"No execution samples for DLQ retry: {skill_id}")
                return False

            quality_score = await self.quality_calculator.calculate(samples, skill_id=skill_id)

            await self._optimization_queue.put((samples[0].skill, quality_score))

            logger.info(f"DLQ task retried: {task_id}, skill: {skill_id}")
            return True

        except Exception as e:
            logger.error(f"DLQ retry failed for {task_id}: {e}")
            self._dead_letter_queue.append(task)
            return False

    def clear_dlq(self) -> int:
        """清空死信队列"""
        return self._dead_letter_queue.clear()
