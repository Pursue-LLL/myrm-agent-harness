import time

from myrm_agent_harness.core.security.consumer_action_guard import (
    ActionEvaluationVerdictEnum,
    ConsumerActionTypeEnum,
    ConsumerGuardPolicy,
    ConsumerOrderSpec,
    ConsumerRealWorldActionGuardSuite,
)


def _make_order(
    quantity: int = 1,
    unit_price: float = 12.0,
    item_name: str = "Mexican Burrito",
    delivery_address: str = "742 Evergreen Terrace, Springfield",
    recipient_phone: str = "13800138000",
    merchant_id: str = "burrito_palace_01",
    action_type: ConsumerActionTypeEnum = ConsumerActionTypeEnum.FOOD_DELIVERY,
) -> ConsumerOrderSpec:
    total = quantity * unit_price
    return ConsumerOrderSpec(
        order_id="ord-test-001",
        agent_id="agent-home-grandma",
        action_type=action_type,
        item_name=item_name,
        quantity=quantity,
        unit_price=unit_price,
        total_amount=total,
        recipient_name="Grandma Smith",
        recipient_phone=recipient_phone,
        delivery_address=delivery_address,
        merchant_id=merchant_id,
        timestamp=time.time(),
    )


def test_grandma_100_burritos_triggers_quantity_sanity_check() -> None:
    suite = ConsumerRealWorldActionGuardSuite()
    policy = ConsumerGuardPolicy(max_item_quantity=5, max_single_action_amount=100.0)

    # 1. Normal order: 2 burritos -> Allowed
    normal_order = _make_order(quantity=2, unit_price=8.5)
    res_normal = suite.evaluate_order(normal_order, policy)
    assert res_normal.is_allowed is True
    assert res_normal.verdict == ActionEvaluationVerdictEnum.ALLOW_AUTONOMOUS

    # 2. Grandma mistakenly orders 100 burritos ($850) -> Blocked, requires HITL confirmation
    huge_order = _make_order(quantity=100, unit_price=8.5)
    res_huge = suite.evaluate_order(huge_order, policy)
    assert res_huge.is_allowed is False
    assert res_huge.verdict == ActionEvaluationVerdictEnum.REQUIRES_HUMAN_CONFIRMATION
    assert res_huge.requires_hitl is True
    assert res_huge.confirmation_card_summary is not None
    assert "Mexican Burrito x 100" in res_huge.confirmation_card_summary
    assert "exceeds common-sense ceiling of 5 units" in res_huge.message


def test_velocity_limiter_blocks_rapid_fire_orders() -> None:
    suite = ConsumerRealWorldActionGuardSuite()
    policy = ConsumerGuardPolicy(velocity_window_seconds=900.0, max_actions_per_window=1)
    now = time.time()

    order = _make_order(quantity=1, unit_price=15.0)

    # 1st order evaluated & confirmed
    res1 = suite.evaluate_order(order, policy, current_time=now)
    assert res1.is_allowed is True
    suite.confirm_and_record_order(order, current_time=now)

    # 2nd order 10 seconds later -> Tripped velocity limit
    res2 = suite.evaluate_order(order, policy, current_time=now + 10.0)
    assert res2.is_allowed is False
    assert res2.verdict == ActionEvaluationVerdictEnum.VELOCITY_RATE_LIMITED

    # 3rd order after 15 minutes window (905s) -> Allowed
    res3 = suite.evaluate_order(order, policy, current_time=now + 905.0)
    assert res3.is_allowed is True


def test_address_invariance_gate_blocks_unknown_destination() -> None:
    suite = ConsumerRealWorldActionGuardSuite()
    policy = ConsumerGuardPolicy(
        allowlisted_addresses=["742 Evergreen Terrace, Springfield"],
        allowlisted_phones=["13800138000"],
    )

    # Trusted address
    safe_order = _make_order(delivery_address="742 Evergreen Terrace, Springfield")
    assert suite.evaluate_order(safe_order, policy).is_allowed is True

    # Untrusted address drift (potential prompt injection / delivery hijack)
    hacked_order = _make_order(delivery_address="Unknown Attacker Drop Zone, Elm St 999")
    res_hacked = suite.evaluate_order(hacked_order, policy)
    assert res_hacked.is_allowed is False
    assert res_hacked.verdict == ActionEvaluationVerdictEnum.UNTRUSTED_ADDRESS_BLOCKED
    assert "not found in approved address whitelist" in res_hacked.message


def test_daily_spend_blast_radius_ceiling() -> None:
    suite = ConsumerRealWorldActionGuardSuite()
    policy = ConsumerGuardPolicy(
        daily_spend_ceiling=200.0,
        max_single_action_amount=150.0,
        max_actions_per_window=10,
    )
    now = time.time()

    # Order 1: $120 spent
    order1 = _make_order(quantity=1, unit_price=120.0)
    assert suite.evaluate_order(order1, policy, current_time=now).is_allowed is True
    suite.confirm_and_record_order(order1, current_time=now)
    assert suite.get_agent_daily_spent("agent-home-grandma", current_time=now) == 120.0

    # Order 2: Attempt $90 more (Total $210 > $200 ceiling) -> Blocked
    order2 = _make_order(quantity=1, unit_price=90.0)
    res2 = suite.evaluate_order(order2, policy, current_time=now + 60.0)
    assert res2.is_allowed is False
    assert res2.verdict == ActionEvaluationVerdictEnum.DAILY_BUDGET_EXCEEDED
    assert res2.requires_hitl is True


def test_consumer_guard_telemetry_metrics() -> None:
    suite = ConsumerRealWorldActionGuardSuite()
    policy = ConsumerGuardPolicy()
    suite.evaluate_order(_make_order(quantity=1, unit_price=10.0), policy)

    metrics = suite.get_metrics()
    assert metrics.total_evaluations == 1
    assert metrics.autonomous_approvals == 1
