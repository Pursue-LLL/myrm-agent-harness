"""Anomaly Detector

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillOptimizationStorage (POS: 存储Protocol)
- .types.AnomalyReport, RootCause (POS: 异常类型)

[OUTPUT]
- AnomalyDetector: 异常检测器

[POS]
Anomaly detection tool (framework layer). Identifies quality regressions using 3-sigma method.

"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .protocols import SkillOptimizationStorage
from .types import AnomalyReport, RootCause

if TYPE_CHECKING:
    from .types import SkillQualityScore


class AnomalyDetector:
    """Anomaly Detector for Skill Quality

    Detects sudden quality drops/spikes using 3-sigma method.

    Detection Method:
    - Calculate mean and std dev from historical data
    - Flag data points > 3 std dev from mean as anomalies
    - Classify severity: low (3σ), medium (4σ), high (5σ), critical (6σ)
    - Root cause analysis: Identify primary factor (token, duration, errors)

    Features:
    - Real-time detection: Identify anomalies as they occur
    - Severity classification: Prioritize critical issues
    - Root cause analysis: Understand what changed
    - Impact assessment: Count affected users/sessions

    Design:
    - Statistical method: Simple 3-sigma, no ML overhead
    - Framework-level: Pure computation, no dependencies
    - Efficient: O(N) time complexity where N = historical samples

    Usage:
        ```python
        from myrm_agent_harness.agent.skills.optimization import (
            InMemoryStorage,
            AnomalyDetector)

        storage = InMemoryStorage()
        detector = AnomalyDetector(storage)

        # Detect anomalies in last 7 days
        anomalies = await detector.detect_quality_anomalies(days=7)

        for anomaly in anomalies:
            if anomaly.severity in ["high", "critical"]:
                print(f"ALERT: {anomaly.skill_id} quality dropped!")
                print(f"Root cause: {anomaly.root_cause.primary_cause}")
        ```
    """

    def __init__(self, storage: SkillOptimizationStorage):
        """Initialize anomaly detector

        Args:
            storage: SkillOptimizationStorage for historical data access
        """
        self._storage = storage

    async def detect_quality_anomalies(self, days: int = 7, sigma_threshold: float = 3.0) -> list[AnomalyReport]:
        """Detect quality anomalies across all skills

        Args:
            days: Days of historical data to analyze
            sigma_threshold: Number of standard deviations for anomaly (default 3.0)

        Returns:
            List of AnomalyReport sorted by severity descending

        Example:
            ```python
            anomalies = await detector.detect_quality_anomalies(days=7)

            high_severity = [a for a in anomalies if a.severity in ["high", "critical"]]

            for anomaly in high_severity:
                print(f"{anomaly.skill_id}: Z-score {anomaly.z_score:.2f}")
            ```
        """
        top_skills = await self._storage.get_top_skills(limit=100)
        bottom_skills = await self._storage.get_bottom_skills(limit=100)
        all_skill_ids = list(set([sid for sid, _ in top_skills + bottom_skills]))

        anomalies: list[AnomalyReport] = []

        for skill_id in all_skill_ids:
            history = await self._storage.get_quality_history(skill_id, days=days)

            if len(history) < 10:
                continue

            recent_report = await self._detect_skill_anomaly(skill_id, history, sigma_threshold)

            if recent_report:
                anomalies.append(recent_report)

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        anomalies.sort(key=lambda a: (severity_order.get(a.severity, 4), a.z_score), reverse=True)

        return anomalies

    async def detect_skill_anomaly(
        self, skill_id: str, days: int = 30, sigma_threshold: float = 3.0
    ) -> AnomalyReport | None:
        """Detect anomaly for specific skill

        Args:
            skill_id: Skill to analyze
            days: Days of historical data
            sigma_threshold: Sigma threshold for detection

        Returns:
            AnomalyReport if anomaly detected, None otherwise

        Example:
            ```python
            anomaly = await detector.detect_skill_anomaly("pdf-generator", days=30)

            if anomaly:
                print(f"Anomaly detected at {anomaly.timestamp}")
                print(f"Primary cause: {anomaly.root_cause.primary_cause}")
            ```
        """
        history = await self._storage.get_quality_history(skill_id, days=days)

        if len(history) < 10:
            return None

        return await self._detect_skill_anomaly(skill_id, history, sigma_threshold)

    async def _detect_skill_anomaly(
        self, skill_id: str, history: list[tuple[datetime, SkillQualityScore]], sigma_threshold: float
    ) -> AnomalyReport | None:
        """Internal: Detect anomaly from history data"""
        if len(history) < 10:
            return None

        scores = [score.overall_score for _, score in history]

        mean_quality = sum(scores) / len(scores)
        std_quality = self._std(scores)

        if std_quality == 0:
            return None

        most_recent_ts, most_recent_score = history[-1]
        z_score = abs((most_recent_score.overall_score - mean_quality) / std_quality)

        if z_score < sigma_threshold:
            return None

        severity = self._classify_severity(z_score)

        root_cause = await self._analyze_root_cause(skill_id, history)

        return AnomalyReport(
            skill_id=skill_id,
            timestamp=most_recent_ts,
            quality_score=most_recent_score.overall_score,
            z_score=z_score,
            root_cause=root_cause,
            impact_user_count=1,
            severity=severity,
            detected_at=datetime.now(),
        )

    async def _analyze_root_cause(self, skill_id: str, history: list[tuple[datetime, SkillQualityScore]]) -> RootCause:
        """Analyze root cause of quality change"""
        if len(history) < 2:
            return RootCause(
                primary_cause="insufficient_data", token_delta=0.0, duration_delta=0.0, error_rate_delta=0.0
            )

        baseline_scores = [score for _, score in history[:-5]]
        recent_scores = [score for _, score in history[-5:]]

        if not baseline_scores or not recent_scores:
            return RootCause(
                primary_cause="insufficient_data", token_delta=0.0, duration_delta=0.0, error_rate_delta=0.0
            )

        baseline_token_eff = sum(s.token_efficiency for s in baseline_scores) / len(baseline_scores)
        recent_token_eff = sum(s.token_efficiency for s in recent_scores) / len(recent_scores)
        token_delta = recent_token_eff - baseline_token_eff

        baseline_exec_time = sum(s.execution_time for s in baseline_scores) / len(baseline_scores)
        recent_exec_time = sum(s.execution_time for s in recent_scores) / len(recent_scores)
        duration_delta = recent_exec_time - baseline_exec_time

        baseline_success_rate = sum(s.success_rate for s in baseline_scores) / len(baseline_scores)
        recent_success_rate = sum(s.success_rate for s in recent_scores) / len(recent_scores)
        error_rate_delta = baseline_success_rate - recent_success_rate

        causes = {
            "token_efficiency": abs(token_delta),
            "execution_time": abs(duration_delta),
            "error_rate": abs(error_rate_delta),
        }

        primary_cause = max(causes, key=causes.get)

        return RootCause(
            primary_cause=primary_cause,
            token_delta=token_delta,
            duration_delta=duration_delta,
            error_rate_delta=error_rate_delta,
            details={
                "baseline_token_eff": baseline_token_eff,
                "recent_token_eff": recent_token_eff,
                "baseline_exec_time": baseline_exec_time,
                "recent_exec_time": recent_exec_time,
                "baseline_success_rate": baseline_success_rate,
                "recent_success_rate": recent_success_rate,
            },
        )

    @staticmethod
    def _classify_severity(z_score: float) -> str:
        """Classify anomaly severity based on z-score"""
        if z_score >= 6.0:
            return "critical"
        elif z_score >= 5.0:
            return "high"
        elif z_score >= 4.0:
            return "medium"
        else:
            return "low"

    @staticmethod
    def _std(values: list[float]) -> float:
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance**0.5
