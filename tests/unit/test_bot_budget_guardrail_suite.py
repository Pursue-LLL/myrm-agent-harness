"""Unit test suite for Autonomous Bot Budget Guardrail and Token Ceiling Circuit Breaker."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.bot_budget_guardrail import (
    AutonomousBotBudgetGuardrail,
    BotBudgetQuota,
    BudgetSandboxMode,
    CircuitBreakerState,
)


@pytest.fixture
def guardrail() -> AutonomousBotBudgetGuardrail:
    rail = AutonomousBotBudgetGuardrail()
    rail.reset_all()
    return rail


def test_unregistered_bot_fail_closed(guardrail: AutonomousBotBudgetGuardrail) -> None:
    res = guardrail.consume_budget("unknown-bot", tokens=1000, cost_usd=0.01)
    assert res.allowed is False
    assert res.state == CircuitBreakerState.OPEN_FROZEN
    assert "not registered" in (res.rejection_reason or "")


def test_normal_consumption_under_threshold(guardrail: AutonomousBotBudgetGuardrail) -> None:
    quota = BotBudgetQuota(
        bot_id="feishu-digest-bot",
        bot_name="Feishu Daily Digest Bot",
        sandbox_mode=BudgetSandboxMode.ISOLATED_SANDBOX,
        token_ceiling=100_000,
        cost_ceiling_usd=1.0,
    )
    guardrail.register_bot_quota(quota)

    # Consume 20%
    res = guardrail.consume_budget("feishu-digest-bot", tokens=20_000, cost_usd=0.2)
    assert res.allowed is True
    assert res.state == CircuitBreakerState.CLOSED
    assert res.current_used_tokens == 20_000
    assert pytest.approx(res.current_used_cost_usd) == 0.2
    assert res.tokens_remaining == 80_000
    assert pytest.approx(res.cost_remaining_usd) == 0.8


def test_soft_warning_half_open_at_eighty_percent(guardrail: AutonomousBotBudgetGuardrail) -> None:
    quota = BotBudgetQuota(
        bot_id="telegram-helper-bot",
        bot_name="Telegram Channel Helper",
        sandbox_mode=BudgetSandboxMode.CORE_PROTECTED,
        token_ceiling=100_000,
        cost_ceiling_usd=2.0,
    )
    guardrail.register_bot_quota(quota)

    # Consume 85%
    res = guardrail.consume_budget("telegram-helper-bot", tokens=85_000, cost_usd=1.7)
    assert res.allowed is True
    assert res.state == CircuitBreakerState.HALF_OPEN
    assert res.tokens_remaining == 15_000


def test_hard_ceiling_trip_and_freeze(guardrail: AutonomousBotBudgetGuardrail) -> None:
    quota = BotBudgetQuota(
        bot_id="cron-scraper-bot",
        bot_name="Cron Scraper Agent",
        sandbox_mode=BudgetSandboxMode.ISOLATED_SANDBOX,
        token_ceiling=50_000,
        cost_ceiling_usd=0.5,
    )
    guardrail.register_bot_quota(quota)

    # First consume 40,000 (80%) -> HALF_OPEN
    res1 = guardrail.consume_budget("cron-scraper-bot", tokens=40_000, cost_usd=0.4)
    assert res1.allowed is True
    assert res1.state == CircuitBreakerState.HALF_OPEN

    # Attempt to consume 20,000 more (total would be 60,000 > 50,000 ceiling) -> trips breaker
    res2 = guardrail.consume_budget("cron-scraper-bot", tokens=20_000, cost_usd=0.2)
    assert res2.allowed is False
    assert res2.state == CircuitBreakerState.OPEN_FROZEN
    assert "Exceeded token or cost ceiling" in (res2.rejection_reason or "")

    # Further calls are strictly blocked while frozen
    res3 = guardrail.consume_budget("cron-scraper-bot", tokens=100, cost_usd=0.001)
    assert res3.allowed is False
    assert res3.state == CircuitBreakerState.OPEN_FROZEN
    assert "Execution suspended to prevent runaway consumption" in (res3.rejection_reason or "")


def test_refuel_and_circuit_breaker_reset(guardrail: AutonomousBotBudgetGuardrail) -> None:
    quota = BotBudgetQuota(
        bot_id="wechat-customer-bot",
        bot_name="WeChat Service Bot",
        sandbox_mode=BudgetSandboxMode.ISOLATED_SANDBOX,
        token_ceiling=10_000,
        cost_ceiling_usd=0.1,
    )
    guardrail.register_bot_quota(quota)

    # Trip breaker
    guardrail.consume_budget("wechat-customer-bot", tokens=15_000, cost_usd=0.15)
    st_before = guardrail.get_quota_status("wechat-customer-bot")
    assert st_before is not None
    assert st_before.state == CircuitBreakerState.OPEN_FROZEN
    assert st_before.frozen_at is not None

    # Refuel with additional 50,000 tokens and $1.0
    refueled = guardrail.refuel_quota(
        "wechat-customer-bot",
        additional_tokens=50_000,
        additional_cost_usd=1.0,
        reset_state=True,
    )
    assert refueled.token_ceiling == 60_000
    assert pytest.approx(refueled.cost_ceiling_usd) == 1.1
    assert refueled.state == CircuitBreakerState.CLOSED
    assert refueled.frozen_at is None

    # Bot can now execute again
    res = guardrail.consume_budget("wechat-customer-bot", tokens=1_000, cost_usd=0.01)
    assert res.allowed is True
    assert res.state == CircuitBreakerState.CLOSED
