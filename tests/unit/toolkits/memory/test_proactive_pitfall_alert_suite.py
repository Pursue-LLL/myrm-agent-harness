"""[POS]: tests/unit/toolkits/memory/test_proactive_pitfall_alert_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for Item 135 ProactivePastPitfallAlertAndDecisionAssistSuite.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.pitfall_alert import (
    AlertSeverity,
    DecisionIntentLevel,
    DispatchChannel,
    PastPitfallRetriever,
    ProactivePitfallAlertEngine,
    ShadowDecisionIntentRecognizer,
)


def test_shadow_decision_intent_recognizer_inquiry_vs_commitment() -> None:
    """Verify intent recognizer distinguishes casual inquiry from structural commitments."""
    recognizer = ShadowDecisionIntentRecognizer()

    # 1. Casual inquiry should be recognized as INQUIRY
    inquiry_text = "如何看待在分布式系统中选用 redis？"
    intent_inq = recognizer.evaluate(inquiry_text)
    assert intent_inq is not None
    assert intent_inq.level == DecisionIntentLevel.INQUIRY

    # 2. Structural commitment should be recognized as COMMITMENT
    commitment_text = "我们决定换成 redis 作为分布式锁方案"
    intent_com = recognizer.evaluate(commitment_text)
    assert intent_com is not None
    assert intent_com.level == DecisionIntentLevel.COMMITMENT
    assert intent_com.confidence >= 0.70
    assert intent_com.target_subject.lower() == "redis"


@pytest.mark.asyncio
async def test_pitfall_retriever_positive_memory_filtering() -> None:
    """Verify retriever does not alert when only positive memories without negative markers exist."""
    retriever = PastPitfallRetriever()
    positive_triad = PastPitfallRetriever.create_triad(
        subject="redis",
        approach="引入 redis 缓存",
        pitfall_lesson="吞吐量提升了 300%，运行稳定顺利，方案非常成功没有任何异常",
        validated_alternative="继续保持",
        severity=AlertSeverity.INFO,
    )
    retriever.seed_records([positive_triad])

    recognizer = ShadowDecisionIntentRecognizer()
    intent = recognizer.evaluate("我们决定选用 redis 作为核心组件")
    assert intent is not None

    matched = await retriever.retrieve_matching_triads(intent)
    # Should be empty because there are no negative failure markers (deadlock, crash, etc.)
    assert len(matched) == 0


@pytest.mark.asyncio
async def test_pitfall_retriever_causal_triad_extraction() -> None:
    """Verify retriever extracts cause-effect-solution triad on negative lessons."""
    retriever = PastPitfallRetriever()
    negative_triad = PastPitfallRetriever.create_triad(
        subject="redis",
        approach="使用 redis 分布式锁",
        pitfall_lesson="未配置看门狗自动续期导致高并发死锁和雪崩故障，惨痛教训！",
        validated_alternative="改用数据库乐观锁 CAS 或 Redlock 结合本地排队",
        severity=AlertSeverity.CRITICAL,
        incident_date="2025-06-15",
        version_context="redis 6.2",
    )
    retriever.seed_records([negative_triad])

    recognizer = ShadowDecisionIntentRecognizer()
    intent = recognizer.evaluate("准备切换到 redis 分布式锁")
    assert intent is not None

    matched = await retriever.retrieve_matching_triads(intent)
    assert len(matched) == 1
    t = matched[0]
    assert t.severity == AlertSeverity.CRITICAL
    assert "死锁" in t.pitfall_lesson
    assert "乐观锁" in t.validated_alternative


def test_drift_mitigation_evaluator() -> None:
    """Verify outdated runtime version triggers drift mitigation note."""
    retriever = PastPitfallRetriever()
    old_triad = PastPitfallRetriever.create_triad(
        subject="python",
        approach="多线程执行",
        pitfall_lesson="全局解释器锁导致性能瓶颈与死锁",
        validated_alternative="多进程架构",
        severity=AlertSeverity.WARNING,
        version_context="Python 2.7",
    )

    # When current runtime is Python 3.12, drift warning should be generated
    warning_diff = retriever.evaluate_drift_warning(old_triad, current_runtime_version="Python 3.12")
    assert "环境演进提示" in warning_diff
    assert "Python 2.7" in warning_diff

    # When version matches, no drift warning
    warning_same = retriever.evaluate_drift_warning(old_triad, current_runtime_version="Python 2.7")
    assert warning_same == ""


@pytest.mark.asyncio
async def test_proactive_engine_flow_and_session_mute() -> None:
    """Verify proactive engine evaluation, dual-channel dispatching, and session mute lifecycle."""
    retriever = PastPitfallRetriever()
    negative_triad = PastPitfallRetriever.create_triad(
        subject="mongodb",
        approach="订单库",
        pitfall_lesson="未配置副本集一致性引起丢数据和事务死锁事故",
        validated_alternative="切换到 Postgres 强一致性事务",
        severity=AlertSeverity.CRITICAL,
    )
    retriever.seed_records([negative_triad])

    engine = ProactivePitfallAlertEngine(retriever=retriever)

    # 1. Casual inquiry -> Skipped silently
    card_inq, rep_inq = await engine.evaluate_input(
        user_input="介绍一下 mongodb 的优缺点？",
        session_id="sess_1",
    )
    assert card_inq is None
    assert rep_inq.alert_generated is False
    assert rep_inq.dispatched_channel == DispatchChannel.SILENT.value

    # 2. Structural commitment -> Triggered frontend callout
    card_com, rep_com = await engine.evaluate_input(
        user_input="我们计划换成 mongodb 作为订单主存储",
        session_id="sess_1",
    )
    assert card_com is not None
    assert rep_com.alert_generated is True
    assert card_com.severity == AlertSeverity.CRITICAL
    assert card_com.dispatch_channel == DispatchChannel.FRONTEND_CALLOUT
    assert "Postgres" in card_com.recommended_action

    # 3. Mute subject for this session -> Subsequent evaluations should be silent
    engine.mute_subject(session_id="sess_1", subject="mongodb")
    card_muted, rep_muted = await engine.evaluate_input(
        user_input="我们计划换成 mongodb 作为订单主存储",
        session_id="sess_1",
    )
    assert card_muted is None
    assert rep_muted.alert_generated is False
    assert rep_muted.dispatched_channel == DispatchChannel.SILENT.value

    # 4. Unmute subject -> Should trigger again
    engine.unmute_subject(session_id="sess_1", subject="mongodb")
    card_unmuted, rep_unmuted = await engine.evaluate_input(
        user_input="我们计划换成 mongodb 作为订单主存储",
        session_id="sess_1",
    )
    assert card_unmuted is not None
    assert rep_unmuted.alert_generated is True
