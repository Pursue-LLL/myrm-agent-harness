"""Unit tests for Dual-Tier Root Admin & User API Key Isolation Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.dual_tier_isolation import (
    AccessPlane,
    DualTierIsolationGate,
    DualTierKeyVault,
    IsolationVerdict,
    KeyTier,
    compute_key_hash,
)


def test_key_vault_registration_and_derivation() -> None:
    vault = DualTierKeyVault()

    # 1. Root admin key
    raw_adm, adm_rec = vault.register_root_admin_key()
    assert raw_adm.startswith("myrm_adm_")
    assert adm_rec.tier == KeyTier.ROOT_ADMIN
    assert adm_rec.user_id is None
    assert adm_rec.key_hash == compute_key_hash(raw_adm)

    lookup_adm = vault.lookup_raw_key(raw_adm)
    assert lookup_adm is not None
    assert lookup_adm.key_id == adm_rec.key_id

    # 2. Derived user key
    raw_usr, usr_rec = vault.derive_user_key(
        user_id="user_alice",
        tenant_id="tenant_org_a",
        agent_id="coder_agent",
    )
    assert raw_usr.startswith("myrm_usr_")
    assert usr_rec.tier == KeyTier.DERIVED_USER
    assert usr_rec.user_id == "user_alice"
    assert usr_rec.tenant_id == "tenant_org_a"
    assert usr_rec.agent_id == "coder_agent"


def test_root_admin_control_plane_permitted_data_plane_blocked() -> None:
    vault = DualTierKeyVault()
    gate = DualTierIsolationGate(vault)

    raw_adm, _ = vault.register_root_admin_key()

    # 1. Admin accessing control plane -> Permitted
    verdict_cp = gate.evaluate_access(
        raw_key=raw_adm,
        requested_plane=AccessPlane.CONTROL_PLANE,
    )
    assert verdict_cp.is_permitted is True
    assert verdict_cp.verdict == IsolationVerdict.PERMITTED
    assert verdict_cp.effective_tier == KeyTier.ROOT_ADMIN

    # 2. Admin attempting to read tenant data/memory -> Blocked (Physical Isolation)
    verdict_dp = gate.evaluate_access(
        raw_key=raw_adm,
        requested_plane=AccessPlane.DATA_PLANE,
        target_user_id="user_alice",
    )
    assert verdict_dp.is_permitted is False
    assert verdict_dp.verdict == IsolationVerdict.BLOCKED_DATA_PLANE_VIOLATION
    assert "Root Admin API keys are strictly forbidden" in verdict_dp.message


def test_derived_user_key_data_plane_and_cross_tenant_breach() -> None:
    vault = DualTierKeyVault()
    gate = DualTierIsolationGate(vault)

    raw_usr, _ = vault.derive_user_key(
        user_id="user_alice",
        tenant_id="tenant_org_a",
    )

    # 1. User accessing own data plane -> Permitted
    verdict_own = gate.evaluate_access(
        raw_key=raw_usr,
        requested_plane=AccessPlane.DATA_PLANE,
        target_user_id="user_alice",
        target_tenant_id="tenant_org_a",
    )
    assert verdict_own.is_permitted is True
    assert verdict_own.verdict == IsolationVerdict.PERMITTED

    # 2. User attempting cross-tenant access to another user's memory -> Blocked
    verdict_cross_user = gate.evaluate_access(
        raw_key=raw_usr,
        requested_plane=AccessPlane.DATA_PLANE,
        target_user_id="user_bob",
    )
    assert verdict_cross_user.is_permitted is False
    assert verdict_cross_user.verdict == IsolationVerdict.BLOCKED_CROSS_TENANT_BREACH
    assert "Cross-tenant breach prevented" in verdict_cross_user.message

    # 3. User attempting cross-tenant access with foreign tenant ID -> Blocked
    verdict_cross_tenant = gate.evaluate_access(
        raw_key=raw_usr,
        requested_plane=AccessPlane.DATA_PLANE,
        target_user_id="user_alice",
        target_tenant_id="tenant_competitor_b",
    )
    assert verdict_cross_tenant.is_permitted is False
    assert verdict_cross_tenant.verdict == IsolationVerdict.BLOCKED_CROSS_TENANT_BREACH

    # 4. User attempting control-plane management/scheduling -> Blocked
    verdict_cp = gate.evaluate_access(
        raw_key=raw_usr,
        requested_plane=AccessPlane.CONTROL_PLANE,
    )
    assert verdict_cp.is_permitted is False
    assert verdict_cp.verdict == IsolationVerdict.BLOCKED_CONTROL_PLANE_VIOLATION
    assert "User API keys cannot access control-plane" in verdict_cp.message


def test_revocation_and_invalid_key_handling() -> None:
    vault = DualTierKeyVault()
    gate = DualTierIsolationGate(vault)

    raw_usr, usr_rec = vault.derive_user_key(user_id="user_charlie")

    # Invalid key
    res_inv = gate.evaluate_access("myrm_invalid_key_123", AccessPlane.DATA_PLANE)
    assert res_inv.is_permitted is False
    assert res_inv.verdict == IsolationVerdict.BLOCKED_INVALID_KEY

    # Revoke key
    rev_ok = vault.revoke_key(usr_rec.key_id)
    assert rev_ok is True

    res_rev = gate.evaluate_access(raw_usr, AccessPlane.DATA_PLANE)
    assert res_rev.is_permitted is False
    assert res_rev.verdict == IsolationVerdict.BLOCKED_REVOKED_KEY
