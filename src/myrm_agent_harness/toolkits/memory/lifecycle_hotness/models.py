"""[POS]: src/myrm_agent_harness/toolkits/memory/lifecycle_hotness/models.py
[INPUT]: Access frequencies, update timestamps, and mathematical decay parameters.
[OUTPUT]: Strongly typed domain models for hotness scoring, exponential time decay, and memory lifecycle stages.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class HotnessLifecycleStage(StrEnum):
    """Lifecycle classification of memory records based on hotness score."""

    COLD = "cold"
    WARM = "warm"
    HOT = "hot"


class HotnessScoringConfig(BaseModel):
    """Configuration governing sigmoid frequency projection, half-life decay, and lifecycle thresholds."""

    default_half_life_days: float = Field(
        default=7.0,
        gt=0.0,
        le=365.0,
        description="Exponential decay half-life in days (default: 7.0 days)",
    )
    blend_alpha: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Weight alpha for hotness score in blended ranking: (1-alpha)*semantic + alpha*hotness",
    )
    cold_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Score threshold below which memory is classified as COLD (candidate for archiving)",
    )
    hot_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Score threshold above which memory is classified as HOT (active focus)",
    )


class MemoryLifecycleItem(BaseModel):
    """Memory item with tracking telemetry and computed lifecycle metrics."""

    id: str = Field(..., description="Unique memory identifier or URI")
    active_count: int = Field(default=0, ge=0, description="Cumulative access or retrieval count")
    updated_at: datetime | None = Field(
        default=None,
        description="Last updated or retrieved timestamp (UTC)",
    )
    semantic_score: float = Field(default=0.0, ge=0.0, description="Raw semantic retrieval score")
    hotness_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Computed hotness score [0.0, 1.0]")
    blended_score: float = Field(default=0.0, ge=0.0, description="Blended score combining semantic and hotness")
    lifecycle_stage: HotnessLifecycleStage = Field(
        default=HotnessLifecycleStage.WARM,
        description="Assigned lifecycle stage",
    )
    metadata: dict[str, str] = Field(default_factory=dict, description="Arbitrary metadata attributes")


class BatchLifecycleClassificationResult(BaseModel):
    """Aggregated result of batch scoring, reranking, and lifecycle stage classification."""

    items: list[MemoryLifecycleItem] = Field(default_factory=list, description="Ranked and classified items")
    cold_count: int = Field(default=0, ge=0, description="Total cold items")
    warm_count: int = Field(default=0, ge=0, description="Total warm items")
    hot_count: int = Field(default=0, ge=0, description="Total hot items")
    avg_hotness: float = Field(default=0.0, ge=0.0, le=1.0, description="Mean hotness score across batch")
