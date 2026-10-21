"""
[INPUT]: DeploymentFunnelEngine, FunnelStageEnum, FeedbackSentiment.
[OUTPUT]: Pytest test cases verifying funnel event recording, conversion rate calculation, drop-off hotspot detection, and nudge loops.
[POS]: myrm-agent-harness/tests/observability/test_deployment_funnel.py
"""

import pytest

from myrm_agent_harness.observability.deployment_funnel import (
    DeploymentFunnelEngine,
    DeploymentFunnelSnapshot,
    FeedbackSentiment,
    FunnelEventRecord,
    FunnelStageEnum,
    StageDropoffMetric,
    UserFeedbackRecord,
)


def test_deployment_funnel_engine_healthy_conversion() -> None:
    engine = DeploymentFunnelEngine()
    dep_id = "dep_test_healthy_01"

    # 10 个用户完成全流程
    for i in range(10):
        uid = f"user_{i}"
        engine.record_event(dep_id, FunnelStageEnum.STAGE_1_VIEW, uid)
        engine.record_event(dep_id, FunnelStageEnum.STAGE_2_ENGAGE, uid)
        engine.record_event(dep_id, FunnelStageEnum.STAGE_3_ACTION, uid)
        engine.record_event(dep_id, FunnelStageEnum.STAGE_4_COMPLETE, uid)

    # 记录正面反馈
    engine.record_feedback(dep_id, FeedbackSentiment.POSITIVE, "Very helpful agent automation!")

    snap = engine.generate_snapshot(dep_id)

    assert isinstance(snap, DeploymentFunnelSnapshot)
    assert snap.deployment_id == dep_id
    assert snap.total_visitors == 10
    assert len(snap.stages) == 4

    # 所有阶段转化率均为 100%，流失率为 0%
    for s in snap.stages:
        assert s.conversion_rate_pct == 100.0
        assert s.dropoff_rate_pct == 0.0

    assert snap.feedback_counts[FeedbackSentiment.POSITIVE.value] == 1
    assert snap.nudge_required is False
    assert snap.nudge_reason is None
    assert snap.autonomous_goal_recommendation is None

    # 验证序列化字典
    raw_dict = snap.to_dict()
    assert raw_dict["deployment_id"] == dep_id
    assert len(raw_dict["stages"]) == 4


def test_deployment_funnel_engine_dropoff_hotspot_and_nudge_loop() -> None:
    engine = DeploymentFunnelEngine()
    dep_id = "dep_test_dropoff_02"

    # 100 个用户到达 STAGE_1_VIEW
    for i in range(100):
        engine.record_event(dep_id, FunnelStageEnum.STAGE_1_VIEW, f"visitor_{i}")

    # 仅 30 个用户进入 STAGE_2_ENGAGE (流失 70%！)
    for i in range(30):
        engine.record_event(dep_id, FunnelStageEnum.STAGE_2_ENGAGE, f"visitor_{i}")

    # 25 个用户触发 STAGE_3_ACTION
    for i in range(25):
        engine.record_event(dep_id, FunnelStageEnum.STAGE_3_ACTION, f"visitor_{i}")

    # 20 个用户到达 STAGE_4_COMPLETE
    for i in range(20):
        engine.record_event(dep_id, FunnelStageEnum.STAGE_4_COMPLETE, f"visitor_{i}")

    # 记录一条负面反馈
    engine.record_feedback(
        dep_id,
        FeedbackSentiment.NEGATIVE,
        "Form parameters were confusing, dropped off immediately.",
    )

    snap = engine.generate_snapshot(dep_id)

    assert snap.total_visitors == 100
    assert snap.dropoff_hotspot_stage == FunnelStageEnum.STAGE_2_ENGAGE
    assert snap.nudge_required is True
    assert "STAGE_2_ENGAGE" in (snap.nudge_reason or "")
    assert "70.0% 流失率" in (snap.nudge_reason or "")

    # 验证自动推荐的高阶自愈改进目标
    assert snap.autonomous_goal_recommendation is not None
    assert "改善部署物在 STAGE_2_ENGAGE 环节的转化率" in snap.autonomous_goal_recommendation
