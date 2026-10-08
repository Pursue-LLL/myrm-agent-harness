"""Unit tests for Zero-Trust Credential Isolation and Git Leakage Shield.

[POS]
Verifies pre-commit diff leak scanning, git commit/push command detection,
ephemeral in-memory secret vault injection, and outbound text redaction.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.git_leak_shield import (
    EphemeralSecretVault,
    GitCommitSecretBlockedError,
    PreCommitSecretProbe,
    RedactedEgressFilter,
)


def test_pre_commit_probe_detects_secrets_in_diff() -> None:
    leaked_diff = (
        "--- a/src/config.py\n"
        "+++ b/src/config.py\n"
        "@@ -10,3 +10,4 @@\n"
        " DB_HOST = 'localhost'\n"
        "+OPENAI_KEY = 'sk-proj-abc1234567890123456789012345678901234567890'\n"
        "+AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
    )

    result = PreCommitSecretProbe.scan_diff(leaked_diff, file_path="src/config.py")
    assert result.has_leak is True
    assert len(result.findings) == 2

    openai_finding = next(f for f in result.findings if f.secret_type == "OpenAI API Key")
    assert openai_finding.suggested_env_var == "OPENAI_API_KEY"
    assert "****" in openai_finding.masked_snippet

    aws_finding = next(f for f in result.findings if f.secret_type == "AWS Access Key ID")
    assert aws_finding.suggested_env_var == "AWS_ACCESS_KEY_ID"

    # assert_commit_safe should raise GitCommitSecretBlockedError
    with pytest.raises(GitCommitSecretBlockedError) as exc_info:
        PreCommitSecretProbe.assert_commit_safe(leaked_diff)
    assert len(exc_info.value.findings) == 2


def test_pre_commit_probe_passes_clean_diff() -> None:
    clean_diff = (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,3 +1,4 @@\n"
        "+import os\n"
        "+api_key = os.getenv('OPENAI_API_KEY')\n"
    )

    result = PreCommitSecretProbe.scan_diff(clean_diff)
    assert result.has_leak is False
    assert len(result.findings) == 0

    # Should not raise
    PreCommitSecretProbe.assert_commit_safe(clean_diff)


def test_pre_commit_probe_command_matcher() -> None:
    assert PreCommitSecretProbe.is_git_commit_or_push("git commit -m 'feat: update'") is True
    assert PreCommitSecretProbe.is_git_commit_or_push("git push origin main") is True
    assert PreCommitSecretProbe.is_git_commit_or_push("GIT COMMIT -a") is True
    assert PreCommitSecretProbe.is_git_commit_or_push("git status") is False
    assert PreCommitSecretProbe.is_git_commit_or_push("git log -n 5") is False


def test_redacted_egress_filter() -> None:
    text = (
        "Agent finished task with OpenAI key sk-proj-1234567890123456789012345678901234567890 "
        "and GitHub token ghp_123456789012345678901234567890123456."
    )

    redacted_res = RedactedEgressFilter.redact_text(text)
    assert redacted_res.redactions_count == 2
    assert "OpenAI API Key" in redacted_res.detected_types
    assert "GitHub Access Token" in redacted_res.detected_types
    assert "sk-proj-1234567890123456789012345678901234567890" not in redacted_res.redacted_text
    assert "ghp_123456789012345678901234567890123456" not in redacted_res.redacted_text
    assert "****" in redacted_res.redacted_text


def test_ephemeral_secret_vault_and_disk_dump_block() -> None:
    vault = EphemeralSecretVault()
    vault.set_secret("STRIPE_SECRET_KEY", "sk_live_999988887777666655554444")
    vault.set_secret("DATABASE_URL", "postgres://user:pass@db.example.com/mydb")

    # 1. In-memory injection
    env = vault.inject_env({"PATH": "/usr/bin"})
    assert env["STRIPE_SECRET_KEY"] == "sk_live_999988887777666655554444"
    assert env["PATH"] == "/usr/bin"

    # 2. Disk persistence attempt blocked
    with pytest.raises(ValueError) as exc_info:
        vault.validate_no_disk_secret_dump(
            ".env",
            "STRIPE_SECRET_KEY=sk_live_999988887777666655554444\n",
        )
    assert "Attempted to write secret credential" in str(exc_info.value)

    # 3. Clean file writes allowed
    vault.validate_no_disk_secret_dump(".env", "PORT=3000\nNODE_ENV=development\n")
