"""
[INPUT]: Raw signals from memory metrics, loop guards, friction ledgers, evals, and health scans.
[OUTPUT]: Strong data models for knowledge compounding five-metric closure and overall health scorecards.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/knowledge_compounding/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CompoundingMetricName(str, Enum):
    """The 5 canonical closure metrics defined for evaluating agent knowledge compounding."""
    REPEATED_ERROR_RATE = "repeated_error_rate"
    KNOWLEDGE_HIT_RATE = "knowledge_hit_rate"
    HUMAN_CORRECTIONS_COUNT = "human_corrections_count"
    FIRST_PASS_SUCCESS_RATE = "first_pass_success_rate"
    STALE_KNOWLEDGE_RATIO = "stale_knowledge_ratio"


class MetricHealthStatus(str, Enum):
    """Health classification for an individual compounding metric."""
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class CompoundingMetricPoint:
    """Immutable data point representing one of the five compounding metrics."""
    name: CompoundingMetricName
    value: float
    unit: str
    status: MetricHealthStatus
    benchmark_threshold: float
    description: str
    data_source_origin: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name.value,
            "value": self.value,
            "unit": self.unit,
            "status": self.status.value,
            "benchmark_threshold": self.benchmark_threshold,
            "description": self.description,
            "data_source_origin": self.data_source_origin,
        }


@dataclass(frozen=True)
class KnowledgeCompoundingHealthSnapshot:
    """Comprehensive snapshot of knowledge compounding health and regression posture."""
    overall_score: float
    compounding_tier: str
    metrics: Dict[str, CompoundingMetricPoint]
    regression_alerts: List[str]
    evaluated_at: str
    window_days: int = 30

    def to_dict(self) -> Dict[str, object]:
        return {
            "overall_score": self.overall_score,
            "compounding_tier": self.compounding_tier,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
            "regression_alerts": list(self.regression_alerts),
            "evaluated_at": self.evaluated_at,
            "window_days": self.window_days,
        }
