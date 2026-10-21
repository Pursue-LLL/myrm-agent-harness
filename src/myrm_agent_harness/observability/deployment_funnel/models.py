"""
[INPUT]: Funnel tracking events, user feedbacks, deployment IDs, and autonomous objectives.
[OUTPUT]: Immutable models for deployment funnel stages, drop-off rates, nudges, and goal recommendations.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/deployment_funnel/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class FunnelStageEnum(str, Enum):
    """Canonical stages for post-deployment user conversion funnel."""
    STAGE_1_VIEW = "STAGE_1_VIEW"          # 用户进入页面/访问应用
    STAGE_2_ENGAGE = "STAGE_2_ENGAGE"      # 用户产生初步交互/输入参数
    STAGE_3_ACTION = "STAGE_3_ACTION"      # 用户触发核心功能执行
    STAGE_4_COMPLETE = "STAGE_4_COMPLETE"  # 用户完成预期闭环目标/消费产出


class FeedbackSentiment(str, Enum):
    """Sentiment classification for post-deployment user feedbacks."""
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


@dataclass(frozen=True)
class FunnelEventRecord:
    """Immutable record of an individual telemetry event along the conversion funnel."""
    event_id: str
    deployment_id: str
    stage: FunnelStageEnum
    user_ident: str
    timestamp: str
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "event_id": self.event_id,
            "deployment_id": self.deployment_id,
            "stage": self.stage.value,
            "user_ident": self.user_ident,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class UserFeedbackRecord:
    """Immutable record of user feedback received on the deployed agent product."""
    feedback_id: str
    deployment_id: str
    sentiment: FeedbackSentiment
    comment: str
    timestamp: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "feedback_id": self.feedback_id,
            "deployment_id": self.deployment_id,
            "sentiment": self.sentiment.value,
            "comment": self.comment,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class StageDropoffMetric:
    """Quantitative metric for an individual funnel stage."""
    stage: FunnelStageEnum
    user_count: int
    conversion_rate_pct: float
    dropoff_rate_pct: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "stage": self.stage.value,
            "user_count": self.user_count,
            "conversion_rate_pct": self.conversion_rate_pct,
            "dropoff_rate_pct": self.dropoff_rate_pct,
        }


@dataclass(frozen=True)
class DeploymentFunnelSnapshot:
    """Comprehensive snapshot of conversion funnel health, hotspots, and nudge loops."""
    deployment_id: str
    total_visitors: int
    stages: List[StageDropoffMetric]
    dropoff_hotspot_stage: Optional[FunnelStageEnum]
    feedback_counts: Dict[str, int]
    nudge_required: bool
    nudge_reason: Optional[str]
    autonomous_goal_recommendation: Optional[str]
    evaluated_at: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "total_visitors": self.total_visitors,
            "stages": [s.to_dict() for s in self.stages],
            "dropoff_hotspot_stage": (
                self.dropoff_hotspot_stage.value
                if self.dropoff_hotspot_stage
                else None
            ),
            "feedback_counts": dict(self.feedback_counts),
            "nudge_required": self.nudge_required,
            "nudge_reason": self.nudge_reason,
            "autonomous_goal_recommendation": self.autonomous_goal_recommendation,
            "evaluated_at": self.evaluated_at,
        }
