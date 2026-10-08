"""
[POS] tests/unit/test_execution_approval_sanitizer_suite.py
[INPUT] myrm_agent_harness.core.security.execution_approval_sanitizer
[OUTPUT] Unit tests for ExecutionApprovalSanitizerFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.execution_approval_sanitizer import (
    ApprovalPayloadRequest,
    ExecutionApprovalSanitizerFacade,
    SecretType,
)


def test_sanitize_api_keys_and_tokens() -> None:
    """Test precise detection and masking of prominent provider keys and tokens."""
    facade = ExecutionApprovalSanitizerFacade()

    raw_command = (
        'curl https://api.openai.com/v1/chat -H "Authorization: Bearer sk-proj-1234567890abcdefghijklmnop" '
        '&& export ANTHROPIC_API_KEY="sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345" '
        '&& git push https://ghp_123456789012345678901234567890123456@github.com/repo '
        '&& aws s3 cp s3://bucket/data . --profile AKIAIOSFODNN7EXAMPLE '
        '&& slack notify --token xoxb-123456789012-1234567890123-abcdefghijklmnopqrstuvwx'
    )

    req = ApprovalPayloadRequest(
        request_id="req-001",
        session_id="sess-001",
        raw_command_or_text=raw_command,
    )

    result = facade.sanitize_payload(req)

    # Assert all keys are removed from sanitized text
    assert "sk-proj-1234567890abcdefghijklmnop" not in result.sanitized_text
    assert "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345" not in result.sanitized_text
    assert "ghp_123456789012345678901234567890123456" not in result.sanitized_text
    assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text
    assert "xoxb-123456789012-1234567890123-abcdefghijklmnopqrstuvwx" not in result.sanitized_text

    # Assert appropriate placeholders are inserted
    assert "[REDACTED:ANTHROPIC_KEY]" in result.sanitized_text
    assert "[REDACTED:GITHUB_TOKEN]" in result.sanitized_text
    assert "[REDACTED:AWS_KEY_ID]" in result.sanitized_text
    assert "[REDACTED:SLACK_TOKEN]" in result.sanitized_text

    assert result.redactions_count >= 5
    assert SecretType.ANTHROPIC_API_KEY in result.detected_secret_types
    assert SecretType.GITHUB_TOKEN in result.detected_secret_types
    assert SecretType.AWS_CREDENTIAL in result.detected_secret_types
    assert SecretType.SLACK_TOKEN in result.detected_secret_types


def test_sanitize_bearer_and_uri_passwords() -> None:
    """Test masking of Bearer tokens and connection URI passwords while preserving connection hosts."""
    facade = ExecutionApprovalSanitizerFacade()

    raw_command = (
        'curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghijklmnopqrstuvwxyz123456" '
        "&& psql postgres://db_admin:UltraSecretDbPassword2026@cluster.internal:5432/finance_prod"
    )

    result = facade.sanitize_raw_text(raw_command)

    assert "UltraSecretDbPassword2026" not in result.sanitized_text
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghijklmnopqrstuvwxyz123456" not in result.sanitized_text

    assert "Bearer [REDACTED:BEARER_TOKEN]" in result.sanitized_text
    assert "postgres://db_admin:[REDACTED:DB_PASSWORD]@cluster.internal:5432/finance_prod" in result.sanitized_text

    assert SecretType.DATABASE_PASSWORD in result.detected_secret_types
    assert SecretType.BEARER_TOKEN in result.detected_secret_types


def test_whitelist_preservation() -> None:
    """Test that legitimate long strings (UUIDs, Git commit SHAs) are not falsely redacted."""
    facade = ExecutionApprovalSanitizerFacade()

    command_with_shas = (
        "git checkout 11bd71901bbe5b1630ceea73d27597364c9af683 "
        "--task-id 123e4567-e89b-12d3-a456-426614174000"
    )

    result = facade.sanitize_raw_text(command_with_shas)

    assert result.sanitized_text == command_with_shas
    assert result.redactions_count == 0
    assert "未检测到敏感明文凭据" in result.badge_summary


def test_generic_high_entropy_secret_detection() -> None:
    """Test generic key-value assignment detecting high-entropy unknown secrets."""
    facade = ExecutionApprovalSanitizerFacade()

    command_with_generic = 'export API_KEY="K9j#m$Q2vL!pZ8wX7rT4yU1iO3eR5tY"'
    result = facade.sanitize_raw_text(command_with_generic)

    assert "K9j#m$Q2vL!pZ8wX7rT4yU1iO3eR5tY" not in result.sanitized_text
    assert "[REDACTED:HIGH_ENTROPY_SECRET]" in result.sanitized_text
    assert SecretType.GENERIC_HIGH_ENTROPY_SECRET in result.detected_secret_types


def test_badge_summary_and_metrics() -> None:
    """Test audit badge formatting and operational metric counters."""
    facade = ExecutionApprovalSanitizerFacade()

    clean_res = facade.sanitize_raw_text("ls -la /tmp")
    assert clean_res.redactions_count == 0
    assert "未检测到敏感明文凭据" in clean_res.badge_summary

    dirty_res = facade.sanitize_raw_text("export GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890")
    assert dirty_res.redactions_count == 1
    assert "已自动脱敏 1 处敏感凭据" in dirty_res.badge_summary

    m = facade.metrics
    assert m.payloads_evaluated_total == 2
    assert m.clean_payloads_total == 1
    assert m.redacted_payloads_total == 1
    assert m.total_secrets_redacted_count == 1
