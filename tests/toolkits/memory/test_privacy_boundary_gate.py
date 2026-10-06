# [POS]: tests/toolkits/memory/test_privacy_boundary_gate.py
# [INPUT]: myrm_agent_harness.toolkits.memory.privacy_gate
# [OUTPUT]: Unit test suite for memory privacy boundary gate and allowlist matching
"""Unit tests for typed memory privacy boundary, exclusion rules, and secret detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.privacy_gate import (
    DeterministicSecretDetector,
    MemoryPrivacyBoundaryGate,
    MemoryPrivacyConfig,
    PathAndExclusionMatcher,
    PrivacyBoundaryViolationError,
    PrivacySensitivityLevel,
    PrivacyViolationType,
)


def test_deterministic_secret_detector_scanning_and_redaction() -> None:
    """Verify regex scanner detects and redacts diverse credentials with zero LLM tokens."""
    detector = DeterministicSecretDetector()

    sample_text = (
        "Here are our keys:\n"
        "sk-ant-api03-abcdef1234567890abcdef1234567890-XYZ12\n"
        "DATABASE_URL=postgres://app_user:s3cr3t_pass@db.internal:5432/app\n"
        "export GITHUB_TOKEN=ghp_123456789012345678901234567890123456\n"
        "password = 'my_super_secret_password'\n"
        "Clean operational line: adopted PostgreSQL for ACID compliance."
    )

    findings = detector.scan(sample_text)
    assert len(findings) >= 4

    types_detected = {f.violation_type for f in findings}
    assert PrivacyViolationType.API_KEY in types_detected
    assert PrivacyViolationType.CONNECTION_URI in types_detected
    assert PrivacyViolationType.PASSWORD_FIELD in types_detected

    redacted_text, _ = detector.redact(sample_text)
    assert "sk-ant-" not in redacted_text
    assert "s3cr3t_pass" not in redacted_text
    assert "ghp_" not in redacted_text
    assert "my_super_secret_password" not in redacted_text
    assert "[REDACTED:API_KEY]" in redacted_text
    assert "[REDACTED:CONNECTION_URI]" in redacted_text
    assert "adopted PostgreSQL for ACID compliance" in redacted_text


def test_private_key_block_detection() -> None:
    """Verify asymmetric private key blocks are caught and masked."""
    detector = DeterministicSecretDetector()
    priv_key_text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y1u...\n"
        "-----END RSA PRIVATE KEY-----\n"
    )

    findings = detector.scan(priv_key_text)
    assert len(findings) == 1
    assert findings[0].violation_type == PrivacyViolationType.PRIVATE_KEY

    redacted, _ = detector.redact(priv_key_text)
    assert "[REDACTED:PRIVATE_KEY]" in redacted
    assert "BEGIN RSA PRIVATE KEY" not in redacted


def test_path_matcher_default_exclusions_and_allowlist(tmp_path: Path) -> None:
    """Verify sensitive filenames are excluded and allowlist overrides work."""
    matcher = PathAndExclusionMatcher(
        allow_patterns=["*.env.example"],
        exclude_patterns=["*custom_secret*"],
    )

    # Sensitive paths
    assert matcher.is_path_excluded(".env") is True
    assert matcher.is_path_excluded("/app/.env.production") is True
    assert matcher.is_path_excluded("~/.ssh/id_rsa") is True
    assert matcher.is_path_excluded("certs/server.pem") is True
    assert matcher.is_path_excluded("config/custom_secret_file.json") is True

    # Safe paths
    assert matcher.is_path_excluded("src/utils.py") is False
    assert matcher.is_path_excluded("docs/architecture.md") is False

    # Whitelisted path override
    assert matcher.is_path_excluded(".env.example") is False


def test_myrmignore_file_parsing(tmp_path: Path) -> None:
    """Verify .myrmignore rules are parsed and applied correctly."""
    ignore_file = tmp_path / ".myrmignore"
    ignore_file.write_text(
        "# Comments should be ignored\n"
        "\n"
        "*.private.json\n"
        "internal_docs/*\n",
        encoding="utf-8",
    )

    matcher = PathAndExclusionMatcher(ignore_file_path=ignore_file)
    assert matcher.is_path_excluded("data.private.json") is True
    assert matcher.is_path_excluded("internal_docs/roadmap.md") is True
    assert matcher.is_path_excluded("public_docs/roadmap.md") is False


def test_gate_check_clean_content_passes() -> None:
    """Verify clean content passes with PUBLIC sensitivity and unchanged text."""
    gate = MemoryPrivacyBoundaryGate()
    clean_text = "We configured FastAPI with Uvicorn and SQLite for memory caching."

    res = gate.check(clean_text, source_path="app/config.py")
    assert res.passed is True
    assert res.sensitivity_level == PrivacySensitivityLevel.PUBLIC
    assert len(res.findings) == 0
    assert res.redacted_content == clean_text
    assert res.violation_reason is None


def test_gate_enforce_hard_veto_on_critical_secret() -> None:
    """Verify enforce() raises PrivacyBoundaryViolationError on critical secrets."""
    gate = MemoryPrivacyBoundaryGate(config=MemoryPrivacyConfig(block_on_critical=True))
    leak_text = "Here is the key: sk-ant-api03-abcdef1234567890abcdef1234567890-XYZ12"

    with pytest.raises(PrivacyBoundaryViolationError) as exc_info:
        gate.enforce(leak_text)

    assert "Critical secret detected" in str(exc_info.value)


def test_gate_enforce_hard_veto_on_excluded_source_path() -> None:
    """Verify enforce() raises PrivacyBoundaryViolationError if source is an excluded file."""
    gate = MemoryPrivacyBoundaryGate()
    text = "DATABASE_HOST=localhost"

    with pytest.raises(PrivacyBoundaryViolationError) as exc_info:
        gate.enforce(text, source_path=".env.production")

    assert "Excluded File Path" in str(exc_info.value) or "matches excluded" in str(exc_info.value)


def test_gate_sanitize_mode_allows_safe_redacted_text() -> None:
    """Verify sanitize() produces safe text when hard blocking is not triggered."""
    gate = MemoryPrivacyBoundaryGate(config=MemoryPrivacyConfig(block_on_critical=False))
    leak_text = "Database URI: mysql://admin:topsecretpassword@db.example.com/mydb"

    sanitized = gate.sanitize(leak_text)
    assert "topsecretpassword" not in sanitized
    assert "[REDACTED:CONNECTION_URI]" in sanitized


def test_gate_strict_mode_vetoes_any_sensitive_finding() -> None:
    """Verify strict_mode rejects any finding even non-critical ones."""
    gate = MemoryPrivacyBoundaryGate(
        config=MemoryPrivacyConfig(strict_mode=True, block_on_critical=False)
    )
    # Password field is SENSITIVE (not CRITICAL)
    text = "password = 'some_user_pass_123'"

    res = gate.check(text)
    assert res.passed is False
    assert res.sensitivity_level == PrivacySensitivityLevel.SENSITIVE
    assert "Strict mode rejected" in (res.violation_reason or "")
