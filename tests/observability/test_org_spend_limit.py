"""
[INPUT]:
- myrm_agent_harness.observability.org_spend_limit::OrgSharedAgentSpendGovernor
- myrm_agent_harness.observability.org_spend_limit::models

[OUTPUT]:
- Pytest unit tests verifying channel vs personal billing scopes, soft-warn / hard circuit breaker thresholds, and ident-level attribution.

[POS]:
tests/observability/test_org_spend_limit.py — 团队共享智能体组织月度限额与标签归因单元测试。
"""

import pytest

from myrm_agent_harness.observability.org_spend_limit import (
    BillingScope,
    GovernorAction,
    OrgSharedAgentSpendGovernor,
    QuerySpendLabel,
    SpendLimitConfig,
    SpendSurface,
)


def test_spend_governor_budget_guard_and_circuit_breaker() -> None:
    governor = OrgSharedAgentSpendGovernor()
    org_id = "org-corp-alpha"

    # 配置月度预算为 $100，软上限 80% ($80)，硬限额 $100 熔断
    governor.configure_org_budget(
        SpendLimitConfig(
            org_id=org_id,
            monthly_budget_usd=100.0,
            soft_warn_watermark_pct=80.0,
            hard_block_limit_usd=100.0,
            is_circuit_breaker_enabled=True,
        )
    )

    channel_label = QuerySpendLabel(
        org_id=org_id,
        surface=SpendSurface.CHANNEL,
        billing_scope=BillingScope.ORG_SHARED,
        session_id="sess-ch-01",
        requesting_user_id="ident:alice",
        query_tags=["code_review", "team_bot"],
    )

    dm_label = QuerySpendLabel(
        org_id=org_id,
        surface=SpendSurface.DIRECT_MESSAGE,
        billing_scope=BillingScope.PERSONAL_DM,
        session_id="sess-dm-01",
        requesting_user_id="ident:bob",
    )

    # 1. 低水位健康放行
    d1 = governor.pre_check_and_guard(org_id, estimated_cost_usd=15.0, label=channel_label)
    assert d1.action == GovernorAction.ALLOW
    assert d1.is_blocked is False

    # 记录该次消耗 $15.0
    governor.record_spend(org_id, actual_tokens=150_000, actual_cost_usd=15.0, label=channel_label)

    # 2. 个人私聊 (PERSONAL_DM) 绕过组织限额
    d_dm = governor.pre_check_and_guard(org_id, estimated_cost_usd=90.0, label=dm_label)
    assert d_dm.action == GovernorAction.ALLOW
    assert "个人私聊会话已自动记入个人账单" in d_dm.reason

    # 3. 消费累加至 $82.0 触发 80% 软上限告警
    governor.record_spend(org_id, actual_tokens=670_000, actual_cost_usd=67.0, label=channel_label)
    # 当前已消耗 15 + 67 = 82 USD (82%)
    d2 = governor.pre_check_and_guard(org_id, estimated_cost_usd=1.0, label=channel_label)
    assert d2.action == GovernorAction.WARN_APPROACHING
    assert d2.is_blocked is False
    assert d2.utilization_pct >= 80.0

    # 4. 超出 $100 触发硬限额熔断刹车
    d3 = governor.pre_check_and_guard(org_id, estimated_cost_usd=25.0, label=channel_label)
    assert d3.action == GovernorAction.CIRCUIT_BREAKER_BLOCKED
    assert d3.is_blocked is True
    assert "硬限额熔断刹车" in d3.reason


def test_spend_governor_ident_and_surface_attribution() -> None:
    governor = OrgSharedAgentSpendGovernor()
    org_id = "org-tech-beta"

    # Alice 在频道发起的请求
    lbl_alice = QuerySpendLabel(
        org_id=org_id,
        surface=SpendSurface.CHANNEL,
        billing_scope=BillingScope.ORG_SHARED,
        session_id="sess-ch-alice",
        requesting_user_id="ident:alice",
    )
    governor.record_spend(org_id, actual_tokens=100_000, actual_cost_usd=12.5, label=lbl_alice)
    governor.record_spend(org_id, actual_tokens=50_000, actual_cost_usd=6.0, label=lbl_alice)

    # Bob 通过 REST_API 发起的自动化脚本
    lbl_bob = QuerySpendLabel(
        org_id=org_id,
        surface=SpendSurface.REST_API,
        billing_scope=BillingScope.ORG_SHARED,
        session_id="sess-api-bob",
        requesting_user_id="ident:bob",
    )
    governor.record_spend(org_id, actual_tokens=80_000, actual_cost_usd=8.0, label=lbl_bob)

    # 聚合身份归因对账
    attributions = governor.get_user_attributions(org_id)
    assert len(attributions) == 2

    # Alice 支出 $18.5 排名第 1
    assert attributions[0].requesting_user_id == "ident:alice"
    assert attributions[0].total_calls_count == 2
    assert attributions[0].total_spend_usd == 18.5
    assert attributions[0].primary_surface == "CHANNEL"

    # Bob 支出 $8.0 排名第 2
    assert attributions[1].requesting_user_id == "ident:bob"
    assert attributions[1].total_spend_usd == 8.0
    assert attributions[1].primary_surface == "REST_API"

    # 组织总览
    summary = governor.get_org_summary(org_id)
    assert summary["current_spend_usd"] == 26.5
    assert summary["total_records_count"] == 3
