"""Unit tests for Connection and Account Domain Isolation suite."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.domain_isolation import (
    DomainIsolationGuard,
    DomainIsolationRegistry,
)


def test_binding_registration_and_domain_resolution(tmp_path: Path) -> None:
    storage = tmp_path / "domain_store.json"
    registry = DomainIsolationRegistry(storage_path=storage)

    # Default fallback is 'work'
    assert registry.resolve_domain("unknown_connector") == "work"

    # Register work connector
    b_feishu = registry.set_binding(
        connector_id="feishu_enterprise_01",
        domain="work",
        channel="feishu",
        account_id="user_work_99",
    )
    assert b_feishu.domain == "work"
    assert registry.resolve_domain("feishu_enterprise_01") == "work"

    # Register personal connector
    b_wechat = registry.set_binding(
        connector_id="wechat_personal_02",
        domain="personal",
        channel="wechat",
        account_id="wx_openid_123",
    )
    assert b_wechat.domain == "personal"
    assert registry.resolve_domain("wechat_personal_02") == "personal"

    # Filter by domain
    work_list = registry.list_bindings(domain="work")
    personal_list = registry.list_bindings(domain="personal")
    assert len(work_list) == 1
    assert len(personal_list) == 1

    # Reload from disk to verify persistence
    reloaded_registry = DomainIsolationRegistry(storage_path=storage)
    assert reloaded_registry.resolve_domain("wechat_personal_02") == "personal"
    assert reloaded_registry.resolve_domain("feishu_enterprise_01") == "work"


def test_domain_grant_isolation_and_update(tmp_path: Path) -> None:
    registry = DomainIsolationRegistry(storage_path=tmp_path / "grants.json")

    # Initial defaults
    work_grant = registry.get_grant("work")
    personal_grant = registry.get_grant("personal")
    assert work_grant.allow_write is True
    assert work_grant.allow_egress is True
    assert personal_grant.allow_egress is False

    # Disable personal recall & write, work remains untouched
    registry.update_grant("personal", allow_write=False, allow_recall=False)

    updated_personal = registry.get_grant("personal")
    updated_work = registry.get_grant("work")
    assert updated_personal.allow_write is False
    assert updated_personal.allow_recall is False
    assert updated_work.allow_write is True
    assert updated_work.allow_recall is True


def test_write_validation_guard(tmp_path: Path) -> None:
    registry = DomainIsolationRegistry(storage_path=tmp_path / "domain.json")
    guard = DomainIsolationGuard(registry)

    # Default: both allow write
    ok_work, _ = guard.validate_write("work")
    ok_personal, _ = guard.validate_write("personal")
    assert ok_work is True
    assert ok_personal is True

    # Turn off personal write
    registry.update_grant("personal", allow_write=False)
    ok_work2, _ = guard.validate_write("work")
    ok_personal2, msg = guard.validate_write("personal")
    assert ok_work2 is True
    assert ok_personal2 is False
    assert "个人" in msg or "personal" in msg


def test_cross_domain_recall_boundaries(tmp_path: Path) -> None:
    registry = DomainIsolationRegistry(storage_path=tmp_path / "domain.json")
    guard = DomainIsolationGuard(registry)

    # Case 1: Same domain (work -> work)
    allowed, msg, is_cross = guard.validate_recall(
        target_domain="work", active_domain="work", allow_cross_domain=False
    )
    assert allowed is True
    assert is_cross is False

    # Case 2: Cross domain default forbidden (work active, trying to recall personal)
    allowed, msg, is_cross = guard.validate_recall(
        target_domain="personal", active_domain="work", allow_cross_domain=False
    )
    assert allowed is False
    assert is_cross is True
    assert "跨域隔离拦截" in msg

    # Case 3: Cross domain explicitly enabled
    allowed, msg, is_cross = guard.validate_recall(
        target_domain="personal", active_domain="work", allow_cross_domain=True
    )
    assert allowed is True
    assert is_cross is True
    assert "允许跨域召回" in msg

    # Case 4: Target domain recall disabled globally for that domain
    registry.update_grant("personal", allow_recall=False)
    allowed, msg, _ = guard.validate_recall(
        target_domain="personal", active_domain="personal", allow_cross_domain=False
    )
    assert allowed is False
    assert "已被停用" in msg


def test_egress_privacy_redlines(tmp_path: Path) -> None:
    registry = DomainIsolationRegistry(storage_path=tmp_path / "domain.json")
    guard = DomainIsolationGuard(registry)

    # 1. Personal domain egress without explicit confirmation -> Blocked
    decision = guard.evaluate_egress(
        content_domain="personal",
        target_channel="enterprise_slack",
        user_confirmed=False,
    )
    assert decision.allowed is False
    assert decision.requires_user_confirmation is True
    assert "隐私红线触发" in decision.reason
    assert decision.is_cross_domain is True

    # 2. Personal domain egress with explicit confirmation -> Allowed
    decision_confirmed = guard.evaluate_egress(
        content_domain="personal",
        target_channel="enterprise_slack",
        user_confirmed=True,
    )
    assert decision_confirmed.allowed is True
    assert decision_confirmed.requires_user_confirmation is False

    # 3. Work domain egress -> Allowed by default
    decision_work = guard.evaluate_egress(
        content_domain="work",
        target_channel="enterprise_slack",
        user_confirmed=False,
    )
    assert decision_work.allowed is True
    assert decision_work.requires_user_confirmation is False
