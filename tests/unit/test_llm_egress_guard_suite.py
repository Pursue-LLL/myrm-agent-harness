"""Unit tests for LLM Egress Default-Deny & Credential Binding Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.llm_egress_guard import (
    DomainAllowlistRule,
    LlmEgressCredentialBindingError,
    LlmEgressDefaultDenyError,
    LlmEgressGuard,
    LlmEgressPolicy,
    LlmEgressVerdict,
    extract_canonical_host,
    matches_domain_pattern,
)


def test_validator_host_extraction_and_matching() -> None:
    assert extract_canonical_host("https://api.openai.com/v1/chat") == "api.openai.com"
    assert extract_canonical_host("http://api.anthropic.com:443/messages") == "api.anthropic.com"
    assert extract_canonical_host("custom-model.openai.azure.com") == "custom-model.openai.azure.com"

    # Pattern matching
    assert matches_domain_pattern("api.openai.com", "api.openai.com") is True
    assert matches_domain_pattern("api.other.com", "api.openai.com") is False

    # Wildcard matching
    assert matches_domain_pattern("eastus.openai.azure.com", "*.openai.azure.com") is True
    assert matches_domain_pattern("openai.azure.com", "*.openai.azure.com") is True
    assert matches_domain_pattern("malicious.azure.com", "*.openai.azure.com") is False


def test_guard_fail_closed_when_no_policy() -> None:
    guard = LlmEgressGuard()  # No policy set

    res = guard.evaluate_egress("https://api.openai.com/v1/chat/completions")
    assert res.is_permitted is False
    assert res.verdict == LlmEgressVerdict.BLOCKED_NO_POLICY
    assert "no explicit egress policy is active" in res.rationale

    with pytest.raises(LlmEgressDefaultDenyError):
        guard.assert_egress_permitted("https://api.openai.com/v1/chat/completions")


def test_guard_explicit_allowlist_and_default_deny() -> None:
    rule_openai = DomainAllowlistRule(
        rule_id="RULE-OPENAI-01",
        domain_pattern="api.openai.com",
        bound_credential_ids=("cred-openai-prod",),
        require_credential_binding=False,
    )
    rule_azure = DomainAllowlistRule(
        rule_id="RULE-AZURE-01",
        domain_pattern="*.openai.azure.com",
        bound_credential_ids=("cred-azure-key",),
        require_credential_binding=False,
    )
    policy = LlmEgressPolicy(
        policy_id="pol-corp-01",
        allowed_rules=(rule_openai, rule_azure),
        is_default_deny=True,
    )

    guard = LlmEgressGuard(policy)

    # 1. Permitted domains
    res_direct = guard.evaluate_egress("https://api.openai.com/v1/models")
    assert res_direct.is_permitted is True
    assert res_direct.verdict == LlmEgressVerdict.PERMITTED
    assert res_direct.matched_rule_id == "RULE-OPENAI-01"

    res_wildcard = guard.evaluate_egress("https://my-tenant.openai.azure.com/v1")
    assert res_wildcard.is_permitted is True
    assert res_wildcard.verdict == LlmEgressVerdict.PERMITTED
    assert res_wildcard.matched_rule_id == "RULE-AZURE-01"

    # 2. Blocked unlisted domain (Default-Deny)
    res_unlisted = guard.evaluate_egress("https://attacker-webhook.xyz/exfil")
    assert res_unlisted.is_permitted is False
    assert res_unlisted.verdict == LlmEgressVerdict.BLOCKED_DOMAIN_NOT_ALLOWED
    assert "destination domain 'attacker-webhook.xyz' is not on the allowlist" in res_unlisted.rationale


def test_guard_strict_credential_binding() -> None:
    rule_anthropic = DomainAllowlistRule(
        rule_id="RULE-ANTHROPIC-01",
        domain_pattern="api.anthropic.com",
        bound_credential_ids=("cred-anthropic-main",),
        require_credential_binding=True,
    )
    policy = LlmEgressPolicy(
        policy_id="pol-cred-bind",
        allowed_rules=(rule_anthropic,),
        is_default_deny=True,
    )
    guard = LlmEgressGuard(policy)

    # 1. Correct bound credential presented -> Permitted
    res_valid = guard.evaluate_egress(
        target_url_or_domain="https://api.anthropic.com/v1/messages",
        presented_credential_id="cred-anthropic-main",
    )
    assert res_valid.is_permitted is True
    assert res_valid.verdict == LlmEgressVerdict.PERMITTED

    # 2. Mismatched or foreign credential presented -> Blocked
    res_mismatch = guard.evaluate_egress(
        target_url_or_domain="https://api.anthropic.com/v1/messages",
        presented_credential_id="cred-stolen-openai-key",
    )
    assert res_mismatch.is_permitted is False
    assert res_mismatch.verdict == LlmEgressVerdict.BLOCKED_CREDENTIAL_MISMATCH
    assert "Credential binding violation" in res_mismatch.rationale

    with pytest.raises(LlmEgressCredentialBindingError):
        guard.assert_egress_permitted(
            target_url_or_domain="https://api.anthropic.com/v1/messages",
            presented_credential_id="cred-stolen-openai-key",
        )
