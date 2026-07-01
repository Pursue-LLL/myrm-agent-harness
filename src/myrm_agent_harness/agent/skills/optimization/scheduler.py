"""Optimization Scheduler

[INPUT]
- .protocols.SkillExecutionProvider (POS: execution event provider)
- .quality_calculator.QualityCalculator (POS: quality score calculator)
- .types.* (POS: core optimization types)
- .event_emitter.EventEmitter (POS: event emitter)
- agent.hooks.HookRegistry (POS: hook registry)
- scheduler_monitoring_mixin (POS: monitoring and trigger APIs)
- scheduler_batch_mixin (POS: batch optimization APIs)
- scheduler_queue_mixin (POS: queue worker APIs)
- scheduler_resilience_mixin (POS: cooldown, circuit breaker, DLQ, metrics)

[OUTPUT]
- OptimizationScheduler: optimization scheduler aggregate root

[POS]
Optimization scheduler (framework layer). Automates the skill optimization workflow.
Composes monitoring, batch, queue, and resilience mixins via multiple inheritance.
MRO order is fixed: Monitoring before Batch before Queue before Resilience
(locked by tests/architecture/test_mixin_mro.py).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from myrm_agent_harness.core.hooks import HookRegistryProtocol

from .scheduler_batch_mixin import OptimizationSchedulerBatchMixin
from .scheduler_monitoring_mixin import OptimizationSchedulerMonitoringMixin
from .scheduler_queue_mixin import OptimizationSchedulerQueueMixin
from .scheduler_resilience_mixin import OptimizationSchedulerResilienceMixin

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata

    from .config import OptimizationConfig
    from .event_emitter import EventEmitter
    from .optimizer import SkillOptimizer
    from .protocols import SkillExecutionProvider
    from .quality_calculator import QualityCalculator
    from .types import SkillQualityScore

logger = logging.getLogger(__name__)


class OptimizationScheduler(
    OptimizationSchedulerMonitoringMixin,
    OptimizationSchedulerBatchMixin,
    OptimizationSchedulerQueueMixin,
    OptimizationSchedulerResilienceMixin,
):
    """优化调度器

    完整实现自动化skill优化流程。
    """

    def __init__(
        self,
        optimizer: SkillOptimizer,
        execution_provider: SkillExecutionProvider,
        quality_calculator: QualityCalculator,
        config: OptimizationConfig,
        event_emitter: EventEmitter | None = None,
        hook_registry: HookRegistryProtocol | None = None,
        metrics_provider: object | None = None,
        anomaly_detector: object | None = None,
    ):
        self.optimizer = optimizer
        self.execution_provider = execution_provider
        self.quality_calculator = quality_calculator
        self.config = config
        self.metrics_provider = metrics_provider
        self.anomaly_detector = anomaly_detector

        from .event_emitter import EventEmitter

        self.event_emitter = event_emitter or EventEmitter()

        self._cooldown_tracker: dict[str, datetime] = {}
        self._circuit_breaker: dict[str, int] = defaultdict(int)

        self._optimization_queue: asyncio.Queue[tuple[SkillMetadata, SkillQualityScore, str | None]] = asyncio.Queue()
        self._queue_worker_task: asyncio.Task | None = None

        self._batch_tasks: dict[str, dict[str, Any]] = {}
        self._batch_cancel_tokens: dict[str, asyncio.Event] = {}
        self._batch_bg_tasks: dict[str, asyncio.Task[None]] = {}
        self._bg_tasks: set[asyncio.Task[None]] = set()

        self._metrics: dict[str, int] = {
            "optimization_total": 0,
            "optimization_success": 0,
            "optimization_failed": 0,
        }

        from .dlq import DeadLetterQueue

        dlq_path = getattr(config.monitoring, "dlq_persist_path", None)
        self._dead_letter_queue = DeadLetterQueue(maxlen=1000, persist_path=dlq_path)

        self._monitoring_task: asyncio.Task | None = None

        if hook_registry:
            self._register_hooks(hook_registry)
