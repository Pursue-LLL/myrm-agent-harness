"""Optimization Scheduler

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillExecutionProvider (POS: 执行事件提供者)
- .quality_calculator.QualityCalculator (POS: 质量计算器)
- .types.* (POS: 核心类型)
- .event_emitter.EventEmitter (POS: 事件发射器)
- agent.hooks.HookRegistry (POS: Hook注册表)

[OUTPUT]
- OptimizationScheduler: 优化调度器类

[POS]
Optimization scheduler (framework layer). Automates the skill optimization workflow.

"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from myrm_agent_harness.core.hooks import HookRegistryProtocol

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata

    from .config import OptimizationConfig
    from .event_emitter import EventEmitter
    from .optimizer import SkillOptimizer
    from .protocols import SkillExecutionProvider
    from .quality_calculator import QualityCalculator
    from .types import SkillQualityScore

logger = logging.getLogger(__name__)


class OptimizationScheduler:
    """优化调度器

    完整实现自动化skill优化流程。

    Args:
        optimizer: Skill优化器
        execution_provider: 执行数据提供者（Protocol接口）
        quality_calculator: 质量计算器
        config: 优化配置
        event_emitter: 事件发射器（可选，用于解耦通知）
        hook_registry: Hook注册表（可选，用于实时监控）
        metrics_provider: Skill metrics提供者（可选，用于funnel分析）
    """

    def __init__(
        self,
        optimizer: SkillOptimizer,
        execution_provider: SkillExecutionProvider,
        quality_calculator: QualityCalculator,
        config: OptimizationConfig,
        event_emitter: EventEmitter | None = None,
        hook_registry: HookRegistryProtocol | None = None,
        metrics_provider: object | None = None,  # SkillMetricsProvider type hint
        anomaly_detector: object | None = None,  # AnomalyDetector type hint
    ):
        self.optimizer = optimizer
        self.execution_provider = execution_provider
        self.quality_calculator = quality_calculator
        self.config = config
        self.metrics_provider = metrics_provider
        self.anomaly_detector = anomaly_detector

        # 事件发射器（解耦通知机制）
        from .event_emitter import EventEmitter

        self.event_emitter = event_emitter or EventEmitter()

        # 冷却期追踪 {skill_id: last_optimization_time}
        self._cooldown_tracker: dict[str, datetime] = {}

        # 断路器追踪 {skill_id: consecutive_failures}
        self._circuit_breaker: dict[str, int] = defaultdict(int)

        # 异步队列系统（F2）
        self._optimization_queue: asyncio.Queue[tuple[SkillMetadata, SkillQualityScore]] = asyncio.Queue()
        self._queue_worker_task: asyncio.Task | None = None

        # 批量任务追踪（F6简化版）
        self._batch_tasks: dict[str, dict[str, Any]] = {}
        self._bg_tasks: set[asyncio.Task[None]] = set()

        # Metrics统计（F8）
        self._metrics: dict[str, int] = {
            "optimization_total": 0,
            "optimization_success": 0,
            "optimization_failed": 0,
        }

        from .dlq import DeadLetterQueue

        dlq_path = getattr(config.monitoring, "dlq_persist_path", None)
        self._dead_letter_queue = DeadLetterQueue(maxlen=1000, persist_path=dlq_path)

        # 监控任务
        self._monitoring_task: asyncio.Task | None = None

        # 注册POST_TOOL_USE Hook（如果提供了HookRegistry）
        if hook_registry:
            self._register_hooks(hook_registry)

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

        # 同时启动queue worker
        await self.start_queue_worker()

    async def stop_monitoring(self) -> None:
        """停止监控和队列worker"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitoring_task
            logger.info("Skill optimization monitoring stopped")

        # 同时停止queue worker
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
            # 1. 获取所有skill ID
            skill_ids = await self.execution_provider.get_all_skill_ids()
            logger.info(f"Found {len(skill_ids)} skills to evaluate")

            # 2. 逐个评估
            for skill_id in skill_ids:
                try:
                    await self._evaluate_skill(skill_id)
                except Exception as e:
                    logger.error(f"Failed to evaluate skill {skill_id}: {e}")

            # 3. 异常检测（如果提供了anomaly_detector）
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

                # 自动触发优化
                await self._evaluate_skill(anomaly.skill_id)

        except Exception as e:
            logger.error(f"Failed to detect anomalies: {e}")

    async def _evaluate_skill(self, skill_id: str) -> None:
        """评估单个skill

        Args:
            skill_id: Skill ID
        """
        # 1. 获取执行样本
        samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=7)

        if not samples:
            logger.debug(f"No execution samples for skill: {skill_id}")
            return

        # 2. 计算质量评分（含funnel metrics）
        quality_score = await self.quality_calculator.calculate(samples, skill_id=skill_id)

        # 3. 检查是否需要优化
        if quality_score.overall_score < self.config.monitoring.optimization_threshold:
            logger.info(
                f"Skill {skill_id} quality below threshold: "
                f"{quality_score.overall_score:.2f} < {self.config.monitoring.optimization_threshold}"
            )

            skill_metadata = await self.execution_provider.get_skill_metadata(skill_id)
            if skill_metadata:
                # Load skill content for optimization
                content = await self.execution_provider.get_skill_content(skill_id)
                await self.trigger_optimization(skill_metadata, quality_score, content=content)
            else:
                logger.warning(f"Skill metadata not found for {skill_id}, skipping optimization")

    async def trigger_optimization(
        self, skill: SkillMetadata, quality_score: SkillQualityScore, use_queue: bool = True, content: str | None = None
    ) -> bool:
        """触发skill优化

        检查冷却期和断路器，决定是否触发优化。

        Args:
            skill: Skill元数据
            quality_score: 质量评分
            use_queue: 是否使用队列（默认True，异步非阻塞）

        Returns:
            bool: 是否成功触发优化（队列模式：是否成功入队；直接模式：是否执行成功）
        """
        # 1. 检查质量阈值
        if quality_score.overall_score >= self.config.monitoring.optimization_threshold:
            logger.debug(f"Skill quality above threshold: {skill.name}")
            return False

        # 2. 检查冷却期
        if not self._check_cooldown(skill.name):
            logger.debug(f"Skill in cooldown period: {skill.name}")
            return False

        # 3. 检查断路器
        if self._is_circuit_broken(skill.name):
            logger.warning(f"Circuit breaker tripped for skill: {skill.name}")
            return False

        # 4. 触发优化（队列模式或直接执行）
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
        else:
            try:
                await self._execute_optimization(skill, quality_score, content=content)
                logger.info(f"Skill optimization triggered (direct): {skill.name}")
                return True

            except Exception as e:
                logger.error(f"Skill optimization failed: {skill.name}, error: {e}")
                return False

    def _check_cooldown(self, skill_id: str) -> bool:
        """检查冷却期

        如果skill最近优化过，返回False。
        """
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
        """记录优化失败

        当连续失败次数达到circuit breaker阈值时，任务进入死信队列(DLQ)。

        Args:
            skill_id: Skill ID
            error_message: 失败原因（可选）
        """
        self._circuit_breaker[skill_id] += 1

        # P1-8: 当触发circuit breaker时，任务进入DLQ
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
        """注册Hook System钩子

        Args:
            hook_registry: Hook注册表
        """
        from myrm_agent_harness.agent.hooks import CallableHookDefinition, HookEvent, HookResult

        async def _on_post_tool_use(event_name: str, payload: dict) -> HookResult:  # type: ignore[type-arg]
            """POST_TOOL_USE Hook回调

            轻量级追踪skill执行，实际的质量计算由定时循环处理。
            """
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
        """健康检查

        Returns:
            健康状态字典
        """
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

    async def trigger_batch_optimization(self, skill_ids: list[str], max_concurrent: int = 3, priority: int = 0) -> str:
        """批量触发skill优化（F1）

        使用Semaphore控制并发数，避免过载。

        Args:
            skill_ids: Skill ID列表
            max_concurrent: 最大并发数（默认3）
            priority: 任务优先级（默认0，仅用于记录）

        Returns:
            batch_task_id: 批量任务ID（用于查询进度）
        """
        batch_task_id = f"batch_{uuid.uuid4().hex[:8]}"

        self._batch_tasks[batch_task_id] = {
            "total": len(skill_ids),
            "completed": 0,
            "failed": 0,
            "status": "running",
            "started_at": datetime.now(),
            "skill_ids": skill_ids,
            "priority": priority,
        }

        logger.info(
            f"Batch optimization started: {batch_task_id}, {len(skill_ids)} skills, "
            f"max_concurrent={max_concurrent}, priority={priority}"
        )

        batch_task = asyncio.create_task(
            self._execute_batch_optimization(batch_task_id, skill_ids, max_concurrent)
        )
        self._bg_tasks.add(batch_task)
        batch_task.add_done_callback(self._bg_tasks.discard)

        return batch_task_id

    async def _execute_batch_optimization(self, batch_task_id: str, skill_ids: list[str], max_concurrent: int) -> None:
        """执行批量优化（内部方法）

        Args:
            batch_task_id: 批量任务ID
            skill_ids: Skill ID列表
            max_concurrent: 最大并发数
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def optimize_one(skill_id: str) -> bool:
            """优化单个skill（带并发控制）"""
            async with semaphore:
                try:
                    samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=7)

                    if not samples:
                        logger.warning(f"No execution samples for skill: {skill_id}")
                        return False

                    quality_score = await self.quality_calculator.calculate(samples, skill_id=skill_id)

                    if quality_score.overall_score < self.config.monitoring.optimization_threshold:
                        skill_metadata = await self.execution_provider.get_skill_metadata(skill_id)
                        if skill_metadata:
                            # Load content for optimization
                            content = await self.execution_provider.get_skill_content(skill_id)
                            await self.optimizer.optimize_skill(skill_metadata, quality_score, content=content)
                            logger.info(f"Batch optimization completed for skill: {skill_id}")
                        else:
                            logger.warning(f"Skill metadata not found: {skill_id}")
                            return False
                    else:
                        logger.info(
                            f"Skill quality above threshold, skipping: {skill_id} (score: {quality_score.overall_score})"
                        )

                    return True

                except Exception as e:
                    logger.error(f"Batch optimization error for {skill_id}: {e}")
                    return False

        # P1-6: 支持进度事件，逐个处理任务
        total = len(skill_ids)
        completed = 0
        failed = 0

        # 创建任务并逐个等待，每完成一个发送进度事件
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

            # 发射进度事件 (P1-6)
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

        # 更新最终状态
        self._batch_tasks[batch_task_id].update(
            {
                "completed": completed,
                "failed": failed,
                "status": "completed",
                "completed_at": datetime.now(),
            }
        )

        logger.info(f"Batch optimization completed: {batch_task_id}, succeeded={completed}, failed={failed}")

        await self.event_emitter.emit(
            "batch_optimization_completed",
            {
                "batch_task_id": batch_task_id,
                "total": len(skill_ids),
                "succeeded": completed,
                "failed": failed,
            },
        )

    def get_batch_status(self, batch_task_id: str) -> dict[str, Any] | None:
        """获取批量任务状态（F6）

        Args:
            batch_task_id: 批量任务ID

        Returns:
            任务状态字典，如不存在返回None
        """
        return self._batch_tasks.get(batch_task_id)

    async def start_queue_worker(self) -> None:
        """启动队列worker（F2）

        从队列中取出优化任务并执行。
        """
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
        """队列worker循环（F2）

        从队列中取出优化任务并执行。
        """
        while True:
            try:
                queue_item = await self._optimization_queue.get()

                # Support both old (2-tuple) and new (3-tuple) items for backward compatibility during transition
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
        self, skill: SkillMetadata, quality_score: SkillQualityScore, content: str | None = None
    ) -> None:
        """执行优化（内部方法）

        Args:
            skill: Skill元数据
            quality_score: 质量评分
        """
        # P2-10: Prometheus记录 - 开始
        from . import prometheus_metrics as prom

        prom.record_optimization_start(skill.name)
        start_time = time.time()

        self._metrics["optimization_total"] += 1

        try:
            result = await self.optimizer.optimize_skill(skill, quality_score, content=content)
            duration = time.time() - start_time

            self._record_success(skill.name)
            self._metrics["optimization_success"] += 1

            # P2-10: Prometheus记录 - 成功
            prom.record_optimization_success(skill.name, result.version, duration)

            # P0-1: 记录LLM成本和Token（如果有）
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

            self._record_failure(skill.name, error_message)  # P1-8: 传递error message
            self._metrics["optimization_failed"] += 1

            # P2-10: Prometheus记录 - 失败
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

    async def reload_config(self, new_config: OptimizationConfig) -> None:
        """热加载配置（F9）

        动态更新配置，不中断运行中任务。

        Args:
            new_config: 新配置

        Raises:
            ValueError: 配置验证失败
        """
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
        """获取Prometheus格式指标（F8）

        Returns:
            指标字典（key-value格式，Prometheus可直接消费）

        Examples:
            >>> scheduler.get_metrics()
            {
                "optimization_total": 150,
                "optimization_success": 142,
                "optimization_failed": 8,
                "queue_size": 3,
                "cooldown_count": 20,
                "circuit_breaker_tripped": 2,
                "batch_tasks_count": 5
            }
        """
        circuit_breaker_tripped = sum(
            1
            for failures in self._circuit_breaker.values()
            if failures >= self.config.monitoring.circuit_breaker_threshold
        )

        queue_size = self._optimization_queue.qsize()
        dlq_size = len(self._dead_letter_queue)

        # P2-10: 更新Prometheus Gauge指标
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
            "dlq_size": dlq_size,  # P1-8
        }

    # ==================== P1-8: 死信队列管理 ====================

    def get_dlq_tasks(self) -> list[dict[str, Any]]:
        """获取死信队列中的所有任务

        Returns:
            死信队列任务列表
        """
        return self._dead_letter_queue.get_all()

    async def retry_dlq_task(self, task_id: str) -> bool:
        """手动重试DLQ中的任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功重试
        """
        task = self._dead_letter_queue.find_by_id(task_id)

        if not task:
            logger.warning(f"DLQ task not found: {task_id}")
            return False

        skill_id = task["skill_id"]

        # 重置circuit breaker，允许重试
        self._circuit_breaker[skill_id] = 0

        # 从DLQ移除
        self._dead_letter_queue.remove(task)

        # 获取skill元数据并触发优化
        try:
            samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=7)
            if not samples:
                logger.warning(f"No execution samples for DLQ retry: {skill_id}")
                return False

            quality_score = await self.quality_calculator.calculate(samples, skill_id=skill_id)

            # 入队重新优化
            await self._optimization_queue.put((samples[0].skill, quality_score))

            logger.info(f"DLQ task retried: {task_id}, skill: {skill_id}")
            return True

        except Exception as e:
            logger.error(f"DLQ retry failed for {task_id}: {e}")
            self._dead_letter_queue.append(task)  # 重新加入DLQ
            return False

    def clear_dlq(self) -> int:
        """清空死信队列

        Returns:
            清空的任务数量
        """
        return self._dead_letter_queue.clear()
