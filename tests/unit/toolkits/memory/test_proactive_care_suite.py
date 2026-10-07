"""[POS]: tests/unit/toolkits/memory/test_proactive_care_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for proactive care, vitality evaluation, and schedule rebalancing.
"""

import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory.proactive_care import (
    FatigueLevelKind,
    HealthMetricsRecord,
    ProactiveCareMetaTools,
    ProactiveCareRebalancingService,
    ScheduleTaskItem,
    VitalityAndFatigueEvaluator,
)


def test_evaluator_vitality_scenarios() -> None:
    """Verify vitality evaluation correctly distinguishes normal, mild fatigue, and severe overdraw."""
    evaluator = VitalityAndFatigueEvaluator()

    # Scenario 1: Normal healthy state
    normal_records = [
        HealthMetricsRecord(
            metric_id="m1",
            timestamp=time.time(),
            sleep_duration_hours=7.8,
            deep_sleep_ratio=0.22,
            daily_steps=8500,
            resting_heart_rate=65,
        )
    ]
    report_normal = evaluator.evaluate(
        health_records=normal_records,
        conversational_cues=["今天精神很棒，准备把功能跑通"],
    )
    assert report_normal.fatigue_level == FatigueLevelKind.NORMAL
    assert report_normal.vitality_score >= 0.75

    # Scenario 2: Mild fatigue with short sleep and casual cue
    mild_records = [
        HealthMetricsRecord(
            metric_id="m2",
            timestamp=time.time(),
            sleep_duration_hours=5.8,
            deep_sleep_ratio=0.15,
            daily_steps=4000,
            resting_heart_rate=72,
        )
    ]
    report_mild = evaluator.evaluate(
        health_records=mild_records,
        conversational_cues=["昨晚稍微有点失眠，感觉好累"],
    )
    assert report_mild.fatigue_level == FatigueLevelKind.MILD_FATIGUE
    assert 0.45 <= report_mild.vitality_score < 0.75
    assert len(report_mild.conversational_cues) >= 1

    # Scenario 3: Severe overdraw with acute sleep deprivation and elevated heart rate
    severe_records = [
        HealthMetricsRecord(
            metric_id="m3",
            timestamp=time.time(),
            sleep_duration_hours=4.2,
            deep_sleep_ratio=0.08,
            daily_steps=1800,
            resting_heart_rate=84,
        )
    ]
    report_severe = evaluator.evaluate(
        health_records=severe_records,
        conversational_cues=["通宵赶进度，头痛欲裂，精疲力竭"],
    )
    assert report_severe.fatigue_level == FatigueLevelKind.SEVERE_OVERDRAW
    assert report_severe.vitality_score < 0.45
    assert any("严重不足" in f for f in report_severe.causal_factors)


def test_schedule_rebalance_acts_before_you_ask(tmp_path: Path) -> None:
    """Verify dynamic schedule reduction (30% and 50%) and empathetic care messages."""
    db_file = tmp_path / "proactive_care.db"
    service = ProactiveCareRebalancingService(db_path=db_file)

    tasks = [
        ScheduleTaskItem(
            task_id="t1",
            title="90分钟力量训练与有氧体能",
            scheduled_date="2026-10-08",
            intensity_level=4,
            is_flexible=True,
            original_duration_minutes=90,
        ),
        ScheduleTaskItem(
            task_id="t2",
            title="不可变动的核心架构评审会议",
            scheduled_date="2026-10-08",
            intensity_level=3,
            is_flexible=False,
            original_duration_minutes=60,
        ),
    ]

    # Ingest severe fatigue telemetry
    service.sync_health_metrics(
        HealthMetricsRecord(
            metric_id="m-severe",
            timestamp=time.time(),
            sleep_duration_hours=4.5,
            deep_sleep_ratio=0.09,
            daily_steps=2100,
            resting_heart_rate=82,
        )
    )
    service.record_conversational_cue("赶了一整夜的需求，困死了")

    plan, notification = service.rebalance_schedule_and_care(tasks=tasks, force_notify=True)

    assert plan.fatigue_level == FatigueLevelKind.SEVERE_OVERDRAW
    assert plan.load_reduction_ratio == 0.50
    # Flexible task t1 should be scaled down by 50%
    modified_t1 = next(t for t in plan.tasks_modified if t.task_id == "t1")
    assert modified_t1.adjusted_duration_minutes == 45
    # Non-flexible task t2 must not be shrunk
    modified_t2 = next(t for t in plan.tasks_modified if t.task_id == "t2")
    assert modified_t2.adjusted_duration_minutes == 60

    assert notification is not None
    assert "喘口气" in notification.title
    assert "懂你" in notification.content_message

    service.close()


def test_care_cooldown_gate(tmp_path: Path) -> None:
    """Verify care cooldown prevents nagging spam but allows escalated states."""
    db_file = tmp_path / "cooldown.db"
    service = ProactiveCareRebalancingService(db_path=db_file, cooldown_seconds=3600.0)

    service.sync_health_metrics(
        HealthMetricsRecord(
            metric_id="m-mild",
            timestamp=time.time(),
            sleep_duration_hours=5.5,
            deep_sleep_ratio=0.15,
            daily_steps=5000,
            resting_heart_rate=74,
        )
    )

    tasks = [
        ScheduleTaskItem(
            task_id="task-1",
            title="背部训练",
            scheduled_date="2026-10-08",
            intensity_level=3,
            is_flexible=True,
            original_duration_minutes=60,
        )
    ]

    # First call: notification must be delivered
    _, notif1 = service.rebalance_schedule_and_care(tasks=tasks, force_notify=False)
    assert notif1 is not None

    # Immediate second call with identical level: should be suppressed by cooldown gate
    _, notif2 = service.rebalance_schedule_and_care(tasks=tasks, force_notify=False)
    assert notif2 is None

    # Third call with escalated fatigue to severe: must bypass cooldown gate and deliver
    service.sync_health_metrics(
        HealthMetricsRecord(
            metric_id="m-severe",
            timestamp=time.time() + 10,
            sleep_duration_hours=3.5,
            deep_sleep_ratio=0.05,
            daily_steps=1000,
            resting_heart_rate=88,
        )
    )
    service.record_conversational_cue("通宵干活，头痛欲裂")
    _, notif3 = service.rebalance_schedule_and_care(tasks=tasks, force_notify=False)
    assert notif3 is not None
    assert notif3.fatigue_level == FatigueLevelKind.SEVERE_OVERDRAW

    service.close()


def test_meta_tools_integration() -> None:
    """Verify Agent ProactiveCareMetaTools end-to-end functionality."""
    service = ProactiveCareRebalancingService(db_path=":memory:")
    tools = ProactiveCareMetaTools(service=service)

    # Record cue
    cue_res = tools.record_conversational_fatigue_cue(cue_text="昨晚熬夜赶报告了")
    assert cue_res["status"] is True

    # Evaluate vitality
    report = tools.evaluate_user_vitality()
    assert report.user_id == "default_user"
    assert len(report.conversational_cues) == 1

    # Rebalance schedule proactively
    rebalance_dict = tools.rebalance_schedule_proactively(
        tasks=[
            {
                "task_id": "meta-t1",
                "title": "晨跑 10 公里",
                "scheduled_date": "2026-10-08",
                "intensity_level": 4,
                "is_flexible": True,
                "original_duration_minutes": 60,
            }
        ],
        force_notify=True,
    )
    plan = rebalance_dict["rebalance_plan"]
    assert plan is not None
    assert len(plan.tasks_modified) == 1

    # Read care notifications list
    notifs = service.list_care_notifications()
    assert len(notifs) >= 1
    assert notifs[0].is_read is False

    # Mark as read
    marked = service.mark_notification_read(notifs[0].notification_id)
    assert marked is True
    unread_left = service.list_care_notifications(unread_only=True)
    assert len(unread_left) == 0

    service.close()
