"""单元测试：从行为中涌现的注意力清单、海量通知意图过滤器与言行错位智能对照套件。

[INPUT]
- EmergentAttentionEngine 及相关领域数据类型

[OUTPUT]
- 验证行为轨迹聚合涌现、注意力驱动的消息过滤分流、言行优先级自动化对照与漂移预警。

[POS]
- 位于 tests/agent/context_management/test_emergent_attention_engine.py
"""

import time
import pytest

from myrm_agent_harness.agent.context_management.emergent_attention import (
    ActionTraceEvent,
    EmergentAttentionDossier,
    EmergentAttentionEngine,
    InboundNotification,
    SieveDecision,
    StatedIntention,
    UserActionTraceKind,
)


def test_action_trace_ingestion_and_emergent_focus() -> None:
    """验证多应用行为轨迹逆向提炼涌现出真实注意力流与主焦点。"""
    engine = EmergentAttentionEngine()
    now = time.time()

    traces = [
        ActionTraceEvent(
            trace_id="tr_1",
            channel="slack",
            kind=UserActionTraceKind.IM_REPLY,
            title="Discuss Core Refactor Architecture",
            summary="Aligned with team on database schema migration",
            duration_minutes=45,
            timestamp_epoch=now - 300,
            project_tags=["Project-Core"],
        ),
        ActionTraceEvent(
            trace_id="tr_2",
            channel="github",
            kind=UserActionTraceKind.CODE_COMMIT,
            title="Implement async queue pipeline",
            summary="Refactor context pipeline to async workers, stuck on deadlock bug",
            duration_minutes=75,
            timestamp_epoch=now - 100,
            project_tags=["Project-Core"],
        ),
        ActionTraceEvent(
            trace_id="tr_3",
            channel="email",
            kind=UserActionTraceKind.EMAIL_DISPATCH,
            title="Reply to vendor invoice",
            summary="Approved annual subscription billing",
            duration_minutes=15,
            timestamp_epoch=now - 50,
            project_tags=["Admin-Finance"],
        ),
    ]

    dossier = engine.ingest_action_traces(traces)

    assert dossier.total_tracked_minutes == 135
    assert dossier.primary_focus == "Project-Core"
    assert len(dossier.items) == 2

    core_item = next(it for it in dossier.items if it.project_name == "Project-Core")
    assert core_item.estimated_time_spent_mins == 120
    assert core_item.attention_score == pytest.approx(120 / 135, abs=0.01)
    # 自动识别 blocker 关键字
    assert "Blocked on:" in core_item.current_blocker

    admin_item = next(it for it in dossier.items if it.project_name == "Admin-Finance")
    assert admin_item.estimated_time_spent_mins == 15
    assert admin_item.attention_score == pytest.approx(15 / 135, abs=0.01)


def test_attention_aware_notification_sieve() -> None:
    """验证高信噪比入站消息根据当前注意力焦点智能分流。"""
    engine = EmergentAttentionEngine()
    now = time.time()

    # 构造当前注意力流：用户高度聚焦在 Project-Alpha (80%)，中等关注 Project-Beta (15%)，未关注 Project-Gamma
    traces = [
        ActionTraceEvent(
            trace_id="t1",
            channel="slack",
            kind=UserActionTraceKind.IM_REPLY,
            title="Coding",
            summary="Deep coding session",
            duration_minutes=80,
            timestamp_epoch=now,
            project_tags=["Project-Alpha"],
        ),
        ActionTraceEvent(
            trace_id="t2",
            channel="doc",
            kind=UserActionTraceKind.DOC_EDIT,
            title="Drafting PRD",
            summary="Specification review",
            duration_minutes=15,
            timestamp_epoch=now,
            project_tags=["Project-Beta"],
        ),
        ActionTraceEvent(
            trace_id="t3",
            channel="email",
            kind=UserActionTraceKind.EMAIL_DISPATCH,
            title="Misc task",
            summary="Reading logs",
            duration_minutes=5,
            timestamp_epoch=now,
            project_tags=["Project-Misc"],
        ),
    ]
    dossier = engine.ingest_action_traces(traces)

    # 1. 强制审批事项 -> 必须即时送达
    notif_approval = InboundNotification(
        notification_id="n1",
        channel="slack",
        sender="OpsBot",
        content="Production deployment pending your sign-off",
        urgency_hint="normal",
        project_tag="Project-Misc",
        requires_approval=True,
    )
    res_approval = engine.filter_inbound_notification(notif_approval, dossier)
    assert res_approval.decision == SieveDecision.DELIVER_IMMEDIATELY

    # 2. 匹配主焦点项目的消息 -> 即时送达
    notif_alpha = InboundNotification(
        notification_id="n2",
        channel="slack",
        sender="Alice",
        content="Found a question on Project-Alpha design",
        urgency_hint="normal",
        project_tag="Project-Alpha",
    )
    res_alpha = engine.filter_inbound_notification(notif_alpha, dossier)
    assert res_alpha.decision == SieveDecision.DELIVER_IMMEDIATELY

    # 3. 匹配次要注意力项目 -> 批次摘要
    notif_beta = InboundNotification(
        notification_id="n3",
        channel="feishu",
        sender="Bob",
        content="Updated Beta PRD comment",
        urgency_hint="low",
        project_tag="Project-Beta",
    )
    res_beta = engine.filter_inbound_notification(notif_beta, dossier)
    assert res_beta.decision == SieveDecision.DIGEST_BATCH

    # 4. 无关项目的噪声消息 -> 静默归档
    notif_gamma = InboundNotification(
        notification_id="n4",
        channel="email",
        sender="Newsletter",
        content="Weekly industry digest",
        urgency_hint="low",
        project_tag="Project-Gamma",
    )
    res_gamma = engine.filter_inbound_notification(notif_gamma, dossier)
    assert res_gamma.decision == SieveDecision.SILENT_ARCHIVE


def test_intention_action_diff_and_cognitive_drift() -> None:
    """验证用户口头声称的优先级与实际精力分配的言行错位自动化对比与预警。"""
    engine = EmergentAttentionEngine()
    now = time.time()

    # 真实行为：用户在 Project-Ops 上耗费了 70 分钟，在 Project-Core 上只花了 10 分钟
    traces = [
        ActionTraceEvent(
            trace_id="t1",
            channel="slack",
            kind=UserActionTraceKind.IM_REPLY,
            title="Handling alerts",
            summary="Emergency incident response and log inspection",
            duration_minutes=70,
            timestamp_epoch=now,
            project_tags=["Project-Ops"],
        ),
        ActionTraceEvent(
            trace_id="t2",
            channel="github",
            kind=UserActionTraceKind.CODE_COMMIT,
            title="Core refactor start",
            summary="Draft skeleton",
            duration_minutes=10,
            timestamp_epoch=now,
            project_tags=["Project-Core"],
        ),
        ActionTraceEvent(
            trace_id="t3",
            channel="docs",
            kind=UserActionTraceKind.DOC_EDIT,
            title="Other",
            summary="Notes",
            duration_minutes=20,
            timestamp_epoch=now,
            project_tags=["Project-Docs"],
        ),
    ]
    dossier = engine.ingest_action_traces(traces)

    # 用户声称的意图：Core 是 Top 1 计划投入 70%，Ops 计划投入 10%
    stated_intentions = [
        StatedIntention(project_name="Project-Core", target_percentage=70.0, priority_rank=1),
        StatedIntention(project_name="Project-Ops", target_percentage=10.0, priority_rank=2),
    ]

    report = engine.analyze_intention_action_diff(stated_intentions, dossier)

    assert report.overall_drift_index > 0
    assert len(report.items) == 2
    assert len(report.top_drift_warnings) >= 2

    core_diff = next(it for it in report.items if it.project_name == "Project-Core")
    assert core_diff.is_neglected is True
    assert core_diff.actual_percentage == 10.0
    assert core_diff.diff_percentage == -60.0

    ops_diff = next(it for it in report.items if it.project_name == "Project-Ops")
    assert ops_diff.is_over_invested is True
    assert ops_diff.actual_percentage == 70.0
    assert ops_diff.diff_percentage == 60.0


def test_empty_traces_defensive() -> None:
    """验证空轨迹时的安全退化。"""
    engine = EmergentAttentionEngine()
    dossier = engine.ingest_action_traces([])
    assert dossier.total_tracked_minutes == 0
    assert dossier.primary_focus == "None"
    assert len(dossier.items) == 0
