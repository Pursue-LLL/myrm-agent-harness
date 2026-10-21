"""
[INPUT]: Metric telemetry requests, label cardinality configurations, and path normalization queries.
[OUTPUT]: Pydantic schemas representing label cardinality metrics, memory cap safeguards, and overflow buckets.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/cardinality_cap/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CardinalityStatus(str, Enum):
    """Health classification of metric label cardinality to bound collector memory."""

    HEALTHY = "healthy"  # Under 80% of defined cap
    APPROACHING_CAP = "approaching_cap"  # Between 80% and 100% of defined cap
    OVERFLOWING = "overflowing"  # Cap exceeded, newly encountered labels routed to overflow sentinel


class CardinalityCapConfig(BaseModel):
    """Runtime limits safeguarding Prometheus and collector memory from label explosions."""

    default_cap: int = Field(default=256, ge=1, description="Maximum distinct label values tracked per metric")
    warning_threshold: float = Field(default=0.8, ge=0.5, le=0.99, description="Utilization ratio triggering warning")
    overflow_sentinel: str = Field(default="_overflow_", description="Fallback bucket label value for dropped keys")
    opt_in_paths: List[str] = Field(
        default_factory=lambda: [
            "/api/v1/chat/completions",
            "/api/v1/sessions",
            "/api/v1/tools/execute",
            "/api/v1/system/health",
        ],
        description="Explicitly allowlisted static request paths exempt from overflow capping",
    )


class MetricCardinalityStat(BaseModel):
    """Itemized cardinality utilization and overflow statistics for a monitored metric."""

    metric_name: str = Field(..., description="Name of the Prometheus metric (e.g. http_requests_total)")
    cap_limit: int = Field(default=256, ge=1, description="Configured ceiling for unique label sets")
    tracked_cardinality: int = Field(default=0, ge=0, description="Current count of distinct tracked label values")
    overflow_count: int = Field(default=0, ge=0, description="Total admissions diverted into overflow sentinel bucket")
    total_samples: int = Field(default=0, ge=0, description="Total sample observations processed")
    utilization_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of cap limit utilized")
    status: CardinalityStatus = Field(default=CardinalityStatus.HEALTHY, description="Current health status")
    top_tracked_labels: List[str] = Field(default_factory=list, description="Top active label values")
    label_hits: Dict[str, int] = Field(default_factory=dict, description="Hit counts per label")
