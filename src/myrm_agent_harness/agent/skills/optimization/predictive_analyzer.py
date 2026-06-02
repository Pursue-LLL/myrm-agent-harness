"""Predictive Analyzer

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillOptimizationStorage (POS: 存储Protocol)
- .types.PredictionResult (POS: 预测结果类型)

[OUTPUT]
- PredictiveAnalyzer: 预测分析器

[POS]
Predictive analysis tool (framework layer). Forecasts future quality trends based on historical data.

"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .protocols import SkillOptimizationStorage
from .types import PredictionResult

if TYPE_CHECKING:
    from .types import SkillQualityScore


class PredictiveAnalyzer:
    """Predictive Analyzer for Skill Quality Trends

    Forecasts future skill quality based on historical data patterns.

    Prediction Methods:
    - Simple Linear Regression: Fit line to historical quality scores
    - Trend Classification: Rising, Falling, Stable
    - Confidence Scoring: Based on R² and sample size

    Features:
    - Proactive optimization: Predict quality drops before they happen
    - Capacity planning: Forecast resource needs
    - Early warning: Alert on negative trends
    - Confidence intervals: Quantify prediction uncertainty

    Design:
    - Framework-level: Pure statistical computation
    - Simple algorithms: Linear regression (no deep learning overkill)
    - Efficient: O(N) time complexity where N = historical samples

    Usage:
        ```python
        from myrm_agent_harness.agent.skills.optimization import (
            InMemoryStorage,
            PredictiveAnalyzer)

        storage = InMemoryStorage()
        analyzer = PredictiveAnalyzer(storage)

        # Predict quality trend for next 7 days
        prediction = await analyzer.predict_quality_trend(
            skill_id="pdf-generator",
            forecast_days=7)

        if prediction and prediction.trend == "falling":
            print(f"Alert: Quality predicted to drop to {prediction.predicted_quality:.2f}")
        ```
    """

    def __init__(self, storage: SkillOptimizationStorage):
        """Initialize predictive analyzer

        Args:
            storage: SkillOptimizationStorage for historical data access
        """
        self._storage = storage

    async def predict_quality_trend(
        self, skill_id: str, forecast_days: int = 7, historical_days: int = 30
    ) -> PredictionResult | None:
        """Predict future quality trend using linear regression

        Args:
            skill_id: Skill to analyze
            forecast_days: Days into future to predict
            historical_days: Days of historical data to use

        Returns:
            PredictionResult with trend forecast or None if insufficient data

        Example:
            ```python
            prediction = await analyzer.predict_quality_trend(
                skill_id="pdf-generator",
                forecast_days=7,
                historical_days=30)

            if prediction:
                print(f"Current: {prediction.current_quality:.2f}")
                print(f"Predicted: {prediction.predicted_quality:.2f}")
                print(f"Trend: {prediction.trend} (confidence: {prediction.confidence:.1%})")
            ```
        """
        history = await self._storage.get_quality_history(skill_id, days=historical_days)

        if len(history) < 5:
            return None

        timestamps, scores = self._extract_time_series(history)

        if not timestamps or not scores:
            return None

        current_quality = scores[-1]

        slope, intercept, r_squared = self._linear_regression(timestamps, scores)

        future_timestamp = timestamps[-1] + (forecast_days * 86400)
        predicted_quality = slope * future_timestamp + intercept

        predicted_quality = max(0.0, min(1.0, predicted_quality))

        trend = self._classify_trend(slope, r_squared)

        confidence = self._calculate_confidence(r_squared, len(scores))

        return PredictionResult(
            skill_id=skill_id,
            current_quality=current_quality,
            predicted_quality=predicted_quality,
            trend=trend,
            confidence=confidence,
            forecast_days=forecast_days,
            predicted_at=datetime.now(),
        )

    async def predict_capacity_needs(
        self, skill_id: str, target_quality: float = 0.8, forecast_days: int = 30
    ) -> dict[str, float | int | None]:
        """Predict when skill quality will drop below target

        Args:
            skill_id: Skill to analyze
            target_quality: Minimum acceptable quality threshold
            forecast_days: Maximum days to forecast

        Returns:
            Dictionary with keys:
            - days_until_below_target: Days until quality drops below target (None if won't drop)
            - current_quality: Current quality score
            - predicted_quality: Predicted quality at forecast_days
            - needs_optimization: Boolean whether optimization is needed

        Example:
            ```python
            capacity = await analyzer.predict_capacity_needs(
                skill_id="pdf-generator",
                target_quality=0.8,
                forecast_days=30)

            if capacity["needs_optimization"]:
                print(f"Schedule optimization in {capacity['days_until_below_target']} days")
            ```
        """
        prediction = await self.predict_quality_trend(skill_id, forecast_days)

        if not prediction:
            return {
                "days_until_below_target": None,
                "current_quality": None,
                "predicted_quality": None,
                "needs_optimization": False,
            }

        needs_optimization = prediction.predicted_quality < target_quality

        days_until_below = None
        if needs_optimization and prediction.current_quality >= target_quality:
            history = await self._storage.get_quality_history(skill_id, days=30)
            timestamps, scores = self._extract_time_series(history)

            if timestamps and scores:
                slope, intercept, _ = self._linear_regression(timestamps, scores)

                if slope < 0:
                    days_until_below = int((target_quality - intercept) / slope - timestamps[-1]) // 86400
                    days_until_below = max(0, min(days_until_below, forecast_days))

        return {
            "days_until_below_target": days_until_below,
            "current_quality": prediction.current_quality,
            "predicted_quality": prediction.predicted_quality,
            "needs_optimization": needs_optimization,
        }

    async def find_declining_skills(self, threshold: float = -0.05, forecast_days: int = 7) -> list[PredictionResult]:
        """Find skills with declining quality trends

        Args:
            threshold: Minimum quality drop to flag (negative value)
            forecast_days: Days to forecast

        Returns:
            List of PredictionResult for declining skills

        Example:
            ```python
            declining = await analyzer.find_declining_skills(threshold=-0.1)

            for pred in declining:
                if pred.confidence > 0.7:
                    print(f"ALERT: {pred.skill_id} quality dropping")
            ```
        """
        top_skills = await self._storage.get_top_skills(limit=100)
        skill_ids = [skill_id for skill_id, _ in top_skills]

        declining: list[PredictionResult] = []

        for skill_id in skill_ids:
            prediction = await self.predict_quality_trend(skill_id, forecast_days)

            if not prediction:
                continue

            quality_drop = prediction.predicted_quality - prediction.current_quality

            if quality_drop <= threshold and prediction.trend == "falling":
                declining.append(prediction)

        declining.sort(key=lambda p: p.predicted_quality - p.current_quality)

        return declining

    @staticmethod
    def _extract_time_series(history: list[tuple[datetime, SkillQualityScore]]) -> tuple[list[float], list[float]]:
        """Extract timestamps and quality scores as floats"""
        if not history:
            return [], []

        base_time = history[0][0].timestamp()
        timestamps = [(ts.timestamp() - base_time) for ts, _ in history]
        scores = [score.overall_score for _, score in history]

        return timestamps, scores

    @staticmethod
    def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float, float]:
        """Simple linear regression: y = slope * x + intercept

        Returns:
            (slope, intercept, r_squared)
        """
        n = len(x)

        if n == 0:
            return 0.0, 0.0, 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        denominator = sum((x[i] - mean_x) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0.0
        intercept = mean_y - slope * mean_x

        ss_tot = sum((y[i] - mean_y) ** 2 for i in range(n))
        ss_res = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))

        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

        return slope, intercept, max(0.0, r_squared)

    @staticmethod
    def _classify_trend(slope: float, r_squared: float) -> str:
        """Classify trend as rising, falling, or stable"""
        if r_squared < 0.3:
            return "stable"

        threshold = 0.0001

        if slope > threshold:
            return "rising"
        elif slope < -threshold:
            return "falling"
        else:
            return "stable"

    @staticmethod
    def _calculate_confidence(r_squared: float, sample_size: int) -> float:
        """Calculate prediction confidence score"""
        r_squared_weight = r_squared * 0.7

        sample_weight = min(sample_size / 30.0, 1.0) * 0.3

        confidence = r_squared_weight + sample_weight

        return min(1.0, max(0.0, confidence))
