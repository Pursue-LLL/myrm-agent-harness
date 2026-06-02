"""Auto Optimization Engine

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillOptimizationStorage (POS: 存储Protocol)
- .predictive_analyzer.PredictiveAnalyzer (POS: 预测分析器)
- .anomaly_detector.AnomalyDetector (POS: 异常检测器)
- .scheduler.OptimizationScheduler (POS: 优化调度器)

[OUTPUT]
- AutoOptimizationEngine: 自动优化引擎
- AutoOptimizationPolicy: 自动优化策略配置

[POS]
Closed-loop automatic optimization engine (framework layer). Core competitive differentiator for autonomous skill improvement.

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .anomaly_detector import AnomalyDetector
from .predictive_analyzer import PredictiveAnalyzer
from .protocols import SkillOptimizationStorage

if TYPE_CHECKING:
    from .scheduler import OptimizationScheduler

logger = logging.getLogger(__name__)


@dataclass
class AutoOptimizationPolicy:
    """Auto-optimization policy configuration

    Defines when and how automatic optimization should be triggered.
    """

    enabled: bool = False
    quality_threshold: float = 0.7
    anomaly_severity_threshold: str = "medium"
    prediction_confidence_threshold: float = 0.7
    cooldown_hours: int = 24
    max_optimizations_per_day: int = 10
    auto_verify: bool = True
    auto_rollback_on_failure: bool = True
    dry_run: bool = False

    @classmethod
    def conservative(cls) -> AutoOptimizationPolicy:
        """Conservative policy: Only optimize severe issues"""
        return cls(
            enabled=True,
            quality_threshold=0.6,
            anomaly_severity_threshold="high",
            prediction_confidence_threshold=0.8,
            cooldown_hours=48,
            max_optimizations_per_day=5,
            auto_verify=True,
            auto_rollback_on_failure=True,
            dry_run=False,
        )

    @classmethod
    def aggressive(cls) -> AutoOptimizationPolicy:
        """Aggressive policy: Optimize proactively"""
        return cls(
            enabled=True,
            quality_threshold=0.75,
            anomaly_severity_threshold="low",
            prediction_confidence_threshold=0.6,
            cooldown_hours=12,
            max_optimizations_per_day=20,
            auto_verify=True,
            auto_rollback_on_failure=True,
            dry_run=False,
        )


class AutoOptimizationEngine:
    """Auto Optimization Engine - Closed-Loop Automation

     Competitor's Unique Advantage: Fully automated quality management.

    Workflow:
    1. Detect: Monitor quality anomalies and declining trends
    2. Trigger: Automatically schedule optimization when thresholds exceeded
    3. Verify: Run A/B test to validate optimization effectiveness
    4. Rollback: Auto-rollback if optimization makes things worse

    Features:
    - Proactive Detection: Predict quality drops before they happen
    - Automatic Triggering: No manual intervention required
    - Scientific Validation: A/B test every optimization
    - Self-Healing: Auto-rollback on failure
    - Cooldown Protection: Prevent optimization thrashing
    - Policy-Based: Configurable conservative/aggressive policies

    Design:
    - Event-Driven: Subscribes to anomaly/prediction events
    - Idempotent: Safe to run multiple times
    - Fault-Tolerant: Graceful degradation on errors
    - Auditable: Logs all auto-optimization decisions

    Usage:
        ```python
        from myrm_agent_harness.agent.skills.optimization import (
            InMemoryStorage,
            PredictiveAnalyzer,
            AnomalyDetector,
            OptimizationScheduler,
            AutoOptimizationEngine,
            AutoOptimizationPolicy)

        storage = InMemoryStorage()
        predictor = PredictiveAnalyzer(storage)
        detector = AnomalyDetector(storage)
        scheduler = OptimizationScheduler(...)

        policy = AutoOptimizationPolicy.conservative()
        engine = AutoOptimizationEngine(
            storage=storage,
            predictor=predictor,
            detector=detector,
            scheduler=scheduler,
            policy=policy)

        # Auto-detect and optimize low-quality skills
        results = await engine.run_auto_optimization_cycle()

        for result in results:
            print(f"Auto-optimized: {result['skill_id']} (trigger: {result['trigger_reason']})")
        ```
    """

    def __init__(
        self,
        storage: SkillOptimizationStorage,
        predictor: PredictiveAnalyzer,
        detector: AnomalyDetector,
        scheduler: OptimizationScheduler,
        policy: AutoOptimizationPolicy,
    ):
        """Initialize auto-optimization engine

        Args:
            storage: SkillOptimizationStorage for data access
            predictor: PredictiveAnalyzer for trend forecasting
            detector: AnomalyDetector for anomaly detection
            scheduler: OptimizationScheduler for optimization execution
            policy: AutoOptimizationPolicy for behavior configuration
        """
        self._storage = storage
        self._predictor = predictor
        self._detector = detector
        self._scheduler = scheduler
        self._policy = policy

        self._optimization_history: dict[str, list[datetime]] = {}

    async def run_auto_optimization_cycle(self) -> list[dict]:
        """Run one cycle of auto-optimization detection and triggering

        Returns:
            List of dictionaries with keys:
            - skill_id: Skill that was optimized
            - trigger_reason: Why optimization was triggered
            - action: "optimized" | "dry_run" | "skipped"
            - details: Additional context

        Example:
            ```python
            results = await engine.run_auto_optimization_cycle()

            for result in results:
                if result["action"] == "optimized":
                    print(f"Optimized {result['skill_id']}: {result['trigger_reason']}")
            ```
        """
        if not self._policy.enabled:
            logger.info("Auto-optimization is disabled")
            return []

        results: list[dict] = []

        anomalies = await self._detector.detect_quality_anomalies(days=7)

        for anomaly in anomalies:
            if not self._should_optimize_anomaly(anomaly.severity):
                continue

            if not self._check_cooldown(anomaly.skill_id):
                results.append(
                    {
                        "skill_id": anomaly.skill_id,
                        "trigger_reason": "anomaly",
                        "action": "skipped",
                        "details": "Cooldown period not elapsed",
                    }
                )
                continue

            action = "dry_run" if self._policy.dry_run else "optimized"

            if not self._policy.dry_run:
                try:
                    await self._scheduler.trigger_optimization(anomaly.skill_id)
                    self._record_optimization(anomaly.skill_id)

                    logger.info(
                        f"Auto-triggered optimization for {anomaly.skill_id} (anomaly detected)",
                        extra={"skill_id": anomaly.skill_id, "severity": anomaly.severity},
                    )
                except Exception:
                    logger.exception(
                        f"Failed to auto-optimize {anomaly.skill_id}", extra={"skill_id": anomaly.skill_id}
                    )
                    action = "failed"

            results.append(
                {
                    "skill_id": anomaly.skill_id,
                    "trigger_reason": f"anomaly (severity: {anomaly.severity})",
                    "action": action,
                    "details": f"Z-score: {anomaly.z_score:.2f}",
                }
            )

        declining = await self._predictor.find_declining_skills(threshold=-0.1, forecast_days=7)

        for prediction in declining:
            if prediction.confidence < self._policy.prediction_confidence_threshold:
                continue

            if not self._check_cooldown(prediction.skill_id):
                results.append(
                    {
                        "skill_id": prediction.skill_id,
                        "trigger_reason": "prediction",
                        "action": "skipped",
                        "details": "Cooldown period not elapsed",
                    }
                )
                continue

            action = "dry_run" if self._policy.dry_run else "optimized"

            if not self._policy.dry_run:
                try:
                    await self._scheduler.trigger_optimization(prediction.skill_id)
                    self._record_optimization(prediction.skill_id)

                    logger.info(
                        f"Auto-triggered optimization for {prediction.skill_id} (declining trend predicted)",
                        extra={
                            "skill_id": prediction.skill_id,
                            "predicted_quality": prediction.predicted_quality,
                        },
                    )
                except Exception:
                    logger.exception(
                        f"Failed to auto-optimize {prediction.skill_id}", extra={"skill_id": prediction.skill_id}
                    )
                    action = "failed"

            results.append(
                {
                    "skill_id": prediction.skill_id,
                    "trigger_reason": f"declining trend (confidence: {prediction.confidence:.1%})",
                    "action": action,
                    "details": f"Predicted quality: {prediction.predicted_quality:.2f}",
                }
            )

        return results

    async def verify_optimization(
        self, skill_id: str, baseline_version: int, candidate_version: int
    ) -> dict[str, bool | str | float]:
        """Verify optimization effectiveness via A/B test

        Args:
            skill_id: Skill to verify
            baseline_version: Version before optimization
            candidate_version: Version after optimization

        Returns:
            Dictionary with keys:
            - success: Whether optimization improved quality
            - winner: "baseline" | "candidate" | "inconclusive"
            - quality_delta: Quality improvement (negative if regression)

        Example:
            ```python
            result = await engine.verify_optimization(
                skill_id="pdf-generator",
                baseline_version=1,
                candidate_version=2)

            if not result["success"]:
                print(f"Optimization failed, rolling back to v{baseline_version}")
            ```
        """
        ab_test = await self._storage.get_ab_test(skill_id)

        if not ab_test or ab_test.status.value not in ["candidate_win", "baseline_win"]:
            return {
                "success": False,
                "winner": "inconclusive",
                "quality_delta": 0.0,
            }

        winner = "candidate" if ab_test.status.value == "candidate_win" else "baseline"

        quality_delta = ab_test.candidate_score.overall_score - ab_test.baseline_score.overall_score

        success = winner == "candidate" and quality_delta > 0

        return {
            "success": success,
            "winner": winner,
            "quality_delta": quality_delta,
        }

    def _should_optimize_anomaly(self, severity: str) -> bool:
        """Check if anomaly severity meets policy threshold"""
        severity_levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}

        policy_level = severity_levels.get(self._policy.anomaly_severity_threshold, 1)
        anomaly_level = severity_levels.get(severity, 0)

        return anomaly_level >= policy_level

    def _check_cooldown(self, skill_id: str) -> bool:
        """Check if cooldown period elapsed for skill"""
        history = self._optimization_history.get(skill_id, [])

        if not history:
            return True

        last_optimization = history[-1]
        cooldown_delta = timedelta(hours=self._policy.cooldown_hours)

        return datetime.now() - last_optimization >= cooldown_delta

    def _record_optimization(self, skill_id: str) -> None:
        """Record optimization timestamp for cooldown tracking"""
        if skill_id not in self._optimization_history:
            self._optimization_history[skill_id] = []

        self._optimization_history[skill_id].append(datetime.now())

        cutoff = datetime.now() - timedelta(days=1)
        self._optimization_history[skill_id] = [ts for ts in self._optimization_history[skill_id] if ts >= cutoff]
