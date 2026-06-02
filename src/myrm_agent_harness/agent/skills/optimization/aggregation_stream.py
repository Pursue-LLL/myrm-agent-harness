"""Aggregation Event Stream Integration

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .event_emitter.EventEmitter (POS: 事件系统)
- .protocols.SkillQualityAggregator (POS: 聚合Protocol)

[OUTPUT]
- AggregationStream: 聚合事件流适配器

[POS]
EventEmitter-to-Aggregator bridge. Connects the event system with the aggregation layer.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .event_emitter import EventEmitter
from .protocols import SkillQualityAggregator

if TYPE_CHECKING:
    from .types import SkillQualityScore

logger = logging.getLogger(__name__)


class AggregationStream:
    """Aggregation Event Stream Integration

    Bridge between EventEmitter and Aggregator.
    Listens to skill execution events and triggers aggregation updates.

    Features:
    - Auto-subscribes to relevant events (skill_executed, quality_snapshot)
    - Supports multiple aggregators simultaneously
    - Async event handling for non-blocking updates
    - Error isolation per aggregator

    Design:
    - Event-driven: Updates triggered by events, not polling
    - Decoupled: Aggregators don't directly subscribe to emitter
    - Fault-tolerant: One aggregator failure doesn't affect others

    Usage:
        ```python
        from myrm_agent_harness.agent.skills.optimization import (
            EventEmitter,
            StreamingAggregator,
            AggregationStream)

        emitter = EventEmitter()
        aggregator1 = StreamingAggregator(storage, emitter)
        aggregator2 = AnotherAggregator(storage, emitter)

        stream = AggregationStream(emitter)
        stream.register_aggregator(aggregator1)
        stream.register_aggregator(aggregator2)

        # Both aggregators auto-update on events
        await emitter.emit("skill_executed", {
            "skill_id": "pdf-generator",
            "quality_score": score,
        })
        ```
    """

    def __init__(self, event_emitter: EventEmitter):
        """Initialize aggregation stream

        Args:
            event_emitter: EventEmitter instance for event subscriptions
        """
        self._emitter = event_emitter
        self._aggregators: list[SkillQualityAggregator] = []

        self._emitter.on("skill_executed", self._on_skill_executed)
        self._emitter.on("quality_snapshot", self._on_quality_snapshot)
        self._emitter.on("optimization_completed", self._on_optimization_completed)
        self._emitter.on("aggregation_updated", self._on_aggregation_updated)

    def register_aggregator(self, aggregator: SkillQualityAggregator) -> None:
        """Register aggregator for auto-updates

        Args:
            aggregator: SkillQualityAggregator to receive event-driven updates
        """
        if aggregator not in self._aggregators:
            self._aggregators.append(aggregator)
            logger.info(f"Registered aggregator: {aggregator.__class__.__name__} (total: {len(self._aggregators)})")

    def unregister_aggregator(self, aggregator: SkillQualityAggregator) -> None:
        """Unregister aggregator

        Args:
            aggregator: SkillQualityAggregator to stop receiving updates
        """
        if aggregator in self._aggregators:
            self._aggregators.remove(aggregator)
            logger.info(
                f"Unregistered aggregator: {aggregator.__class__.__name__} (remaining: {len(self._aggregators)})"
            )

    async def _on_skill_executed(self, event: str, payload: dict) -> None:
        """Event handler: skill executed"""
        skill_id: str | None = payload.get("skill_id")
        quality_score: SkillQualityScore | None = payload.get("quality_score")

        if not skill_id or not quality_score:
            logger.warning("skill_executed event missing skill_id or quality_score", extra={"event_data": payload})
            return

        for aggregator in self._aggregators:
            try:
                if hasattr(aggregator, "_on_skill_executed"):
                    await aggregator._on_skill_executed(event, payload)
            except Exception:
                logger.exception(
                    f"Aggregator {aggregator.__class__.__name__} failed to process skill_executed",
                    extra={"skill_id": skill_id},
                )

    async def _on_quality_snapshot(self, event: str, payload: dict) -> None:
        """Event handler: quality snapshot saved"""
        skill_id: str | None = payload.get("skill_id")
        quality_score: SkillQualityScore | None = payload.get("quality_score")

        if not skill_id or not quality_score:
            logger.warning("quality_snapshot event missing skill_id or quality_score", extra={"event_data": payload})
            return

        for aggregator in self._aggregators:
            try:
                if hasattr(aggregator, "_on_quality_updated"):
                    await aggregator._on_quality_updated(event, payload)
            except Exception:
                logger.exception(
                    f"Aggregator {aggregator.__class__.__name__} failed to process quality_snapshot",
                    extra={"skill_id": skill_id},
                )

    async def _on_optimization_completed(self, event: str, payload: dict) -> None:
        """Event handler: optimization completed"""
        skill_id: str | None = payload.get("skill_id")

        if not skill_id:
            logger.warning("optimization_completed event missing skill_id", extra={"event_data": payload})
            return

        for aggregator in self._aggregators:
            try:
                if hasattr(aggregator, "_on_optimization_completed"):
                    await aggregator._on_optimization_completed(event, payload)
            except Exception:
                logger.exception(
                    f"Aggregator {aggregator.__class__.__name__} failed to process optimization_completed",
                    extra={"skill_id": skill_id},
                )

    async def _on_aggregation_updated(self, event: str, payload: dict) -> None:
        """Event handler: aggregation manually updated"""
        logger.debug("aggregation_updated event received", extra={"event_data": payload})
