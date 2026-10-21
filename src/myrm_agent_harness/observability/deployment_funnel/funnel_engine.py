"""
[INPUT]: Funnel events, user feedback submissions, and deployment IDs.
[OUTPUT]: Evaluated DeploymentFunnelSnapshot with drop-off metrics, nudge alerts, and autonomous goal recommendations.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/deployment_funnel/funnel_engine.py
"""

from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional, Set
import uuid

from .models import (
    DeploymentFunnelSnapshot,
    FeedbackSentiment,
    FunnelEventRecord,
    FunnelStageEnum,
    StageDropoffMetric,
    UserFeedbackRecord,
)

_ORDERED_STAGES: List[FunnelStageEnum] = [
    FunnelStageEnum.STAGE_1_VIEW,
    FunnelStageEnum.STAGE_2_ENGAGE,
    FunnelStageEnum.STAGE_3_ACTION,
    FunnelStageEnum.STAGE_4_COMPLETE,
]


class DeploymentFunnelEngine:
    """Thread-safe engine for post-deployment user funnel tracking and feedback nudge loops."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: Dict[str, List[FunnelEventRecord]] = {}
        self._feedbacks: Dict[str, List[UserFeedbackRecord]] = {}

    def record_event(
        self,
        deployment_id: str,
        stage: FunnelStageEnum,
        user_ident: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> FunnelEventRecord:
        """Record an individual user funnel event."""
        with self._lock:
            if deployment_id not in self._events:
                self._events[deployment_id] = []

            event = FunnelEventRecord(
                event_id=f"fe_{uuid.uuid4().hex[:12]}",
                deployment_id=deployment_id,
                stage=stage,
                user_ident=user_ident,
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata=metadata or {},
            )
            self._events[deployment_id].append(event)
            return event

    def record_feedback(
        self,
        deployment_id: str,
        sentiment: FeedbackSentiment,
        comment: str,
    ) -> UserFeedbackRecord:
        """Record user feedback with sentiment tag."""
        with self._lock:
            if deployment_id not in self._feedbacks:
                self._feedbacks[deployment_id] = []

            fb = UserFeedbackRecord(
                feedback_id=f"fb_{uuid.uuid4().hex[:12]}",
                deployment_id=deployment_id,
                sentiment=sentiment,
                comment=comment,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._feedbacks[deployment_id].append(fb)
            return fb

    def generate_snapshot(self, deployment_id: str) -> DeploymentFunnelSnapshot:
        """Compute conversion funnel stages, detect drop-off hotspots, and trigger nudge alerts."""
        with self._lock:
            events = self._events.get(deployment_id, [])
            feedbacks = self._feedbacks.get(deployment_id, [])

            # 1. 统计每个阶段唯一独立用户数
            users_by_stage: Dict[FunnelStageEnum, Set[str]] = {
                stage: set() for stage in _ORDERED_STAGES
            }
            for e in events:
                if e.stage in users_by_stage:
                    users_by_stage[e.stage].add(e.user_ident)

            total_visitors = len(users_by_stage[FunnelStageEnum.STAGE_1_VIEW])

            # 2. 计算各阶段转化率与相对上一步的流失率
            stage_metrics: List[StageDropoffMetric] = []
            prev_count = total_visitors
            max_dropoff_pct = 0.0
            hotspot_stage: Optional[FunnelStageEnum] = None

            for stage in _ORDERED_STAGES:
                curr_count = len(users_by_stage[stage])
                conv_rate = (
                    round((curr_count / total_visitors) * 100.0, 1)
                    if total_visitors > 0
                    else 0.0
                )

                if prev_count > 0:
                    dropoff_pct = round(
                        max(0.0, ((prev_count - curr_count) / prev_count) * 100.0), 1
                    )
                else:
                    dropoff_pct = 0.0

                # 识别最大流失热点阶段（排除入口阶段 STAGE_1）
                if stage != FunnelStageEnum.STAGE_1_VIEW and dropoff_pct > max_dropoff_pct:
                    max_dropoff_pct = dropoff_pct
                    hotspot_stage = stage

                stage_metrics.append(
                    StageDropoffMetric(
                        stage=stage,
                        user_count=curr_count,
                        conversion_rate_pct=conv_rate,
                        dropoff_rate_pct=dropoff_pct,
                    )
                )
                prev_count = curr_count

            # 3. 统计反馈情绪分布
            fb_counts = {
                FeedbackSentiment.POSITIVE.value: 0,
                FeedbackSentiment.NEUTRAL.value: 0,
                FeedbackSentiment.NEGATIVE.value: 0,
            }
            for fb in feedbacks:
                fb_counts[fb.sentiment.value] = fb_counts.get(fb.sentiment.value, 0) + 1

            # 4. 判断是否需要主动 Nudge 告警与推荐高阶目标
            negative_count = fb_counts[FeedbackSentiment.NEGATIVE.value]
            nudge_required = False
            nudge_reason: Optional[str] = None
            goal_recommendation: Optional[str] = None

            reasons: list[str] = []
            if max_dropoff_pct >= 40.0:
                reasons.append(
                    f"阶段 [{hotspot_stage.value if hotspot_stage else 'UNKNOWN'}] 出现显著流失断点 "
                    f"({max_dropoff_pct:.1f}% 流失率)，用户转化受阻。"
                )
            if negative_count > 0:
                reasons.append(f"收到 {negative_count} 条负面用户反馈，需关注交付使用体验。")

            if reasons:
                nudge_required = True
                nudge_reason = " | ".join(reasons)

            if nudge_required:
                hotspot_desc = hotspot_stage.value if hotspot_stage else "关键环节"
                goal_recommendation = (
                    f"请以【改善部署物在 {hotspot_desc} 环节的转化率与用户体验】为高阶目标，"
                    f"自主分析交互瓶颈并提出优化方案。"
                )

            evaluated_at = datetime.now(timezone.utc).isoformat()

            return DeploymentFunnelSnapshot(
                deployment_id=deployment_id,
                total_visitors=total_visitors,
                stages=stage_metrics,
                dropoff_hotspot_stage=hotspot_stage,
                feedback_counts=fb_counts,
                nudge_required=nudge_required,
                nudge_reason=nudge_reason,
                autonomous_goal_recommendation=goal_recommendation,
                evaluated_at=evaluated_at,
            )
