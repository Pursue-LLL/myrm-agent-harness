"""Unit tests for Computer-Use Safe Enclave and Action Replay Audit Deck.

[POS]
Harness core security test suite for Computer-Use action interception,
panic circuit breaker, and audit replay ring buffer.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.desktop_enclave import (
    CriticalActionBlockedError,
    CriticalActionSemanticMatcher,
    CriticalDesktopAction,
    DesktopActionAuditDeck,
    DesktopActionEnclaveGate,
    DesktopActionPanickedError,
    DesktopActionRiskLevel,
    DesktopActionType,
)


def test_semantic_matcher_risk_classification() -> None:
    # 1. Financial
    pay_action = CriticalDesktopAction(
        action_id="act_01",
        action_type=DesktopActionType.MOUSE_CLICK,
        semantic_intent="点击确认付款按钮",
        target_element_text="立即支付 99.00 元",
    )
    risk, cat, reason = CriticalActionSemanticMatcher.evaluate(pay_action)
    assert risk == DesktopActionRiskLevel.CRITICAL
    assert cat == "financial_transaction"
    assert "支付" in reason

    # 2. Destructive
    del_action = CriticalDesktopAction(
        action_id="act_02",
        action_type=DesktopActionType.SYSTEM_COMMAND,
        semantic_intent="清空回收站并抹掉磁盘数据",
        payload_text="empty trash",
    )
    risk, cat, reason = CriticalActionSemanticMatcher.evaluate(del_action)
    assert risk == DesktopActionRiskLevel.CRITICAL
    assert cat == "destructive_deletion"

    # 3. Outbound messaging
    msg_action = CriticalDesktopAction(
        action_id="act_03",
        action_type=DesktopActionType.KEY_PRESS,
        semantic_intent="群发营销短信到外部客户列表",
    )
    risk, cat, reason = CriticalActionSemanticMatcher.evaluate(msg_action)
    assert risk == DesktopActionRiskLevel.CRITICAL
    assert cat == "outbound_messaging"

    # 4. System security tampering
    sec_action = CriticalDesktopAction(
        action_id="act_04",
        action_type=DesktopActionType.TEXT_INPUT,
        semantic_intent="关闭防火墙保护配置",
        payload_text="disable sip",
    )
    risk, cat, reason = CriticalActionSemanticMatcher.evaluate(sec_action)
    assert risk == DesktopActionRiskLevel.CRITICAL
    assert cat == "system_security_tamper"

    # 5. Suspicious
    suspicious_action = CriticalDesktopAction(
        action_id="act_05",
        action_type=DesktopActionType.MOUSE_CLICK,
        semantic_intent="delete draft file",
    )
    risk, cat, reason = CriticalActionSemanticMatcher.evaluate(suspicious_action)
    assert risk == DesktopActionRiskLevel.SUSPICIOUS

    # 6. Safe
    safe_action = CriticalDesktopAction(
        action_id="act_06",
        action_type=DesktopActionType.MOUSE_CLICK,
        semantic_intent="打开系统设置常规偏好",
        target_element_text="General Settings",
    )
    risk, cat, reason = CriticalActionSemanticMatcher.evaluate(safe_action)
    assert risk == DesktopActionRiskLevel.SAFE
    assert cat == "benign"


def test_audit_deck_ring_buffer_and_live_feed() -> None:
    deck = DesktopActionAuditDeck(capacity=3)
    assert deck.capacity == 3

    for i in range(5):
        act = CriticalDesktopAction(
            action_id=f"act_{i}",
            action_type=DesktopActionType.MOUSE_CLICK,
            semantic_intent=f"Intent {i}",
        )
        deck.record_action(
            record_id=f"rec_{i}",
            action=act,
            enclave_verified=True,
            executed=True,
            execution_latency_ms=10.5 * i,
            status="executed",
        )

    records = deck.list_records(limit=10)
    assert len(records) == 3
    # Most recent first
    assert records[0].record_id == "rec_4"
    assert records[1].record_id == "rec_3"
    assert records[2].record_id == "rec_2"

    rec = deck.get_record("rec_3")
    assert rec is not None
    assert rec.action.action_id == "act_3"

    feed = deck.get_live_intent_feed(limit=2)
    assert len(feed) == 2
    assert feed[0]["record_id"] == "rec_4"
    assert feed[0]["status"] == "executed"

    deck.clear()
    assert len(deck.list_records()) == 0


def test_enclave_gate_interception_and_approval_flow() -> None:
    deck = DesktopActionAuditDeck()
    gate = DesktopActionEnclaveGate(audit_deck=deck)

    # 1. Safe action passes through directly
    safe_action = CriticalDesktopAction(
        action_id="act_safe",
        action_type=DesktopActionType.MOUSE_CLICK,
        semantic_intent="滚动查看文档",
    )
    allowed, chal = gate.evaluate_action(safe_action)
    assert allowed is True
    assert chal is None

    # 2. Critical action is intercepted
    crit_action = CriticalDesktopAction(
        action_id="act_pay",
        action_type=DesktopActionType.MOUSE_CLICK,
        semantic_intent="点击确认购买付款",
        target_element_text="立即支付 500 元",
    )
    allowed, chal = gate.evaluate_action(crit_action)
    assert allowed is False
    assert chal is not None
    assert chal.status == "pending"
    assert chal.action.risk_level == DesktopActionRiskLevel.CRITICAL

    # 3. Verify pending challenge listed
    pending = gate.list_pending_challenges()
    assert len(pending) == 1
    assert pending[0].challenge_id == chal.challenge_id

    # 4. Human approval
    approved_action = gate.approve_challenge(chal.challenge_id)
    assert approved_action.action_id == "act_pay"
    assert gate.get_challenge(chal.challenge_id).status == "approved"
    assert len(gate.list_pending_challenges()) == 0

    # 5. Intercept another critical action and reject it
    del_action = CriticalDesktopAction(
        action_id="act_del",
        action_type=DesktopActionType.SYSTEM_COMMAND,
        semantic_intent="永久删除所有本地用户数据",
    )
    allowed, chal2 = gate.evaluate_action(del_action)
    assert allowed is False
    assert chal2 is not None

    with pytest.raises(CriticalActionBlockedError) as exc_info:
        gate.reject_challenge(chal2.challenge_id, reason="User rejected dangerous deletion")
    assert exc_info.value.action_id == "act_del"
    assert gate.get_challenge(chal2.challenge_id).status == "rejected"


def test_enclave_gate_panic_circuit_breaker() -> None:
    deck = DesktopActionAuditDeck()
    gate = DesktopActionEnclaveGate(audit_deck=deck)

    crit_action = CriticalDesktopAction(
        action_id="act_crit",
        action_type=DesktopActionType.MOUSE_CLICK,
        semantic_intent="立即支付",
    )
    allowed, chal = gate.evaluate_action(crit_action)
    assert allowed is False
    assert chal is not None
    assert chal.status == "pending"

    # Trip the panic switch
    assert not gate.is_panicked
    gate.trigger_panic(reason="User pressed physical hardware killswitch")
    assert gate.is_panicked
    assert gate.panic_reason == "User pressed physical hardware killswitch"

    # Pending challenge marked panicked
    updated_chal = gate.get_challenge(chal.challenge_id)
    assert updated_chal is not None
    assert updated_chal.status == "panicked"

    # Any new action evaluation raises DesktopActionPanickedError
    with pytest.raises(DesktopActionPanickedError) as panic_err:
        gate.evaluate_action(
            CriticalDesktopAction(
                action_id="act_subsequent",
                action_type=DesktopActionType.MOUSE_CLICK,
                semantic_intent="普通点击",
            )
        )
    assert "killswitch" in panic_err.value.reason

    # Approving any challenge during panic fails
    with pytest.raises(DesktopActionPanickedError):
        gate.approve_challenge(chal.challenge_id)

    # Reset panic switch restores operations
    gate.reset_panic()
    assert not gate.is_panicked

    safe_action = CriticalDesktopAction(
        action_id="act_recovered",
        action_type=DesktopActionType.MOUSE_CLICK,
        semantic_intent="正常点击",
    )
    allowed_rec, chal_rec = gate.evaluate_action(safe_action)
    assert allowed_rec is True
    assert chal_rec is None
