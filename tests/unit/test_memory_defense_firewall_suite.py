"""Unit tests for Memory Defense Ingestion Firewall and PII Sanitization Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.memory_defense_firewall import (
    DefenseAction,
    DefensePolicy,
    MemoryDefenseFirewall,
    SensitiveCategory,
    get_builtin_patterns,
    get_compiled_patterns,
)


@pytest.fixture
def firewall() -> MemoryDefenseFirewall:
    return MemoryDefenseFirewall()


def test_builtin_patterns_catalog_completeness() -> None:
    patterns = get_builtin_patterns()
    assert len(patterns) >= 40
    compiled = get_compiled_patterns()
    assert len(compiled) == len(patterns)

    # Validate distinct pattern IDs
    ids = [p.pattern_id for p in patterns]
    assert len(ids) == len(set(ids))


def test_clean_text_allow_admission(firewall: MemoryDefenseFirewall) -> None:
    clean_text = "The quick brown fox jumps over the lazy dog and writes normal Python code."
    result = firewall.inspect_and_defend(clean_text)

    assert result.action_taken == DefenseAction.ALLOW
    assert result.is_admitted is True
    assert result.sanitized_text == clean_text
    assert len(result.matches) == 0
    assert result.audit_id.startswith("mdf_")


def test_multiple_secrets_redact_sanitization(firewall: MemoryDefenseFirewall) -> None:
    raw_text = (
        "Here is the OpenAI key: sk-proj-1234567890abcdef1234567890abcdef1234567890 "
        "and GitHub token ghp_111122223333444455556666777788889999 "
        "and my phone number is 13800138000 for emergency contact."
    )

    result = firewall.inspect_and_defend(raw_text)

    assert result.action_taken == DefenseAction.REDACT
    assert result.is_admitted is True
    assert "sk-proj-" not in result.sanitized_text
    assert "ghp_" not in result.sanitized_text
    assert "13800138000" not in result.sanitized_text
    assert "[REDACTED_OPENAI_KEY]" in result.sanitized_text
    assert "[REDACTED_GITHUB_PAT]" in result.sanitized_text
    assert "[REDACTED_PHONE_NUMBER]" in result.sanitized_text
    assert len(result.matches) >= 3


def test_policy_block_hostile_ingestion(firewall: MemoryDefenseFirewall) -> None:
    # 1. Test global BLOCK policy
    raw_text = "Database connection: postgres://admin:superSecretPassword123@localhost:5432/mydb"
    block_policy = DefensePolicy(default_action=DefenseAction.BLOCK)

    result_block = firewall.inspect_and_defend(raw_text, policy=block_policy)
    assert result_block.action_taken == DefenseAction.BLOCK
    assert result_block.is_admitted is False
    assert result_block.sanitized_text == ""
    assert len(result_block.matches) >= 1

    # 2. Test category-specific BLOCK
    selective_policy = DefensePolicy(
        default_action=DefenseAction.REDACT,
        blocked_categories={SensitiveCategory.PRIVATE_KEY},
    )
    rsa_text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
    result_selective = firewall.inspect_and_defend(rsa_text, policy=selective_policy)
    assert result_selective.action_taken == DefenseAction.BLOCK
    assert result_selective.is_admitted is False


def test_false_positive_exemption_whitelist(firewall: MemoryDefenseFirewall) -> None:
    test_token = "ghp_111122223333444455556666777788889999"
    content = f"Mock documentation example token: {test_token}"

    # First check: redacted
    res_before = firewall.inspect_and_defend(content)
    assert res_before.action_taken == DefenseAction.REDACT

    # Add token to exemption whitelist
    firewall.add_exemption(test_token)
    assert test_token in firewall.list_exemptions()

    # Second check: exempted and admitted clean
    res_after = firewall.inspect_and_defend(content)
    assert res_after.action_taken == DefenseAction.ALLOW
    assert res_after.is_admitted is True
    assert test_token in res_after.sanitized_text

    # Remove exemption
    assert firewall.remove_exemption(test_token) is True
    res_final = firewall.inspect_and_defend(content)
    assert res_final.action_taken == DefenseAction.REDACT


def test_audit_records_tracking(firewall: MemoryDefenseFirewall) -> None:
    firewall.inspect_and_defend("Normal memory entry A")
    firewall.inspect_and_defend("Sensitive token: sk-ant-1234567890abcdef1234567890abcdef1234567890")

    records = firewall.get_audit_records(limit=10)
    assert len(records) >= 2
    assert records[-1].action_taken == DefenseAction.REDACT
    assert records[-2].action_taken == DefenseAction.ALLOW
