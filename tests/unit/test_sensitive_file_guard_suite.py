"""Unit tests for Sensitive Vault and Credential File Overwrite Deny Guard Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.sensitive_file_guard import (
    FileWriteOperationType,
    PermissionDeniedSensitiveFileError,
    SensitiveFileCategory,
    SensitiveFileInspection,
    SensitivePathDenyRules,
    SensitiveVaultAndCredentialFileOverwriteDenyGuard,
)


def test_deny_rules_matching() -> None:
    rules = SensitivePathDenyRules()

    # 1. Environment secrets
    assert rules.match_path(".env") is not None
    assert rules.match_path("./.env.local").category == SensitiveFileCategory.ENV_SECRET
    assert rules.match_path("/workspace/subdir/.env.production").category == SensitiveFileCategory.ENV_SECRET

    # 2. Private keys
    assert rules.match_path("server.key").category == SensitiveFileCategory.PRIVATE_KEY
    assert rules.match_path("/etc/ssl/cert.pem").category == SensitiveFileCategory.PRIVATE_KEY
    assert rules.match_path("~/.ssh/id_rsa").category == SensitiveFileCategory.PRIVATE_KEY
    assert rules.match_path("~/.ssh/id_ed25519").category == SensitiveFileCategory.PRIVATE_KEY

    # 3. Password managers & vault files
    assert rules.match_path("~/.config/bitwarden/data.json").category == SensitiveFileCategory.PASSWORD_VAULT
    assert rules.match_path(".myrm/vault.db").category == SensitiveFileCategory.PASSWORD_VAULT
    assert rules.match_path("passwords.kdbx").category == SensitiveFileCategory.PASSWORD_VAULT

    # 4. Cloud and CLI credentials
    assert rules.match_path("~/.aws/credentials").category == SensitiveFileCategory.CLOUD_CREDENTIAL
    assert rules.match_path("~/.kube/config").category == SensitiveFileCategory.CLOUD_CREDENTIAL
    assert rules.match_path("~/.git-credentials").category == SensitiveFileCategory.CLOUD_CREDENTIAL

    # 5. Non-sensitive safe files
    assert rules.match_path("src/index.ts") is None
    assert rules.match_path("tests/unit/test_app.py") is None
    assert rules.match_path("README.md") is None


def test_guard_blocks_unauthorized_mutation() -> None:
    guard = SensitiveVaultAndCredentialFileOverwriteDenyGuard()

    # 1. Unauthorized attempt to overwrite .env
    inspection_bad = SensitiveFileInspection(
        target_path=".env",
        operation_type=FileWriteOperationType.OVERWRITE,
        tool_name="file_write",
        session_id="sess-deny-1",
    )
    decision_bad = guard.inspect_file_operation(inspection_bad)
    assert decision_bad.allowed is False
    assert decision_bad.is_unlocked is False
    assert "strictly denied" in decision_bad.reason

    with pytest.raises(PermissionDeniedSensitiveFileError, match="strictly denied"):
        guard.assert_write_allowed(inspection_bad)

    # 2. Authorized write to non-sensitive file
    inspection_good = SensitiveFileInspection(
        target_path="src/components/button.tsx",
        operation_type=FileWriteOperationType.WRITE,
        tool_name="file_write",
        session_id="sess-deny-1",
    )
    decision_good = guard.inspect_file_operation(inspection_good)
    assert decision_good.allowed is True
    assert decision_good.matched_rule is None


def test_guard_explicit_unlock_workflow() -> None:
    guard = SensitiveVaultAndCredentialFileOverwriteDenyGuard()
    target_file = "/project/.env.local"

    # 1. Initially blocked
    insp_blocked = SensitiveFileInspection(
        target_path=target_file,
        operation_type=FileWriteOperationType.REPLACE,
    )
    assert guard.inspect_file_operation(insp_blocked).allowed is False

    # 2. Issue explicit unlock grant
    grant = guard.unlock_manager.issue_grant(
        target_path=target_file,
        ttl_seconds=120,
        granted_by="user_2fa_confirmed",
    )
    assert grant.unlock_token is not None

    # 3. Write with token succeeds
    insp_unlocked = SensitiveFileInspection(
        target_path=target_file,
        operation_type=FileWriteOperationType.REPLACE,
        unlock_token=grant.unlock_token,
    )
    decision_unlocked = guard.inspect_file_operation(insp_unlocked)
    assert decision_unlocked.allowed is True
    assert decision_unlocked.is_unlocked is True

    # 4. Revoke grant -> blocked again
    assert guard.unlock_manager.revoke_grant(grant.unlock_token) is True
    decision_relocked = guard.inspect_file_operation(insp_unlocked)
    assert decision_relocked.allowed is False


def test_alerts_capture_and_filter() -> None:
    guard = SensitiveVaultAndCredentialFileOverwriteDenyGuard()
    session_id = "sess-alert-test"

    guard.inspect_file_operation(
        SensitiveFileInspection(
            target_path="~/.ssh/id_rsa",
            operation_type=FileWriteOperationType.DELETE,
            session_id=session_id,
        )
    )
    guard.inspect_file_operation(
        SensitiveFileInspection(
            target_path="~/.aws/credentials",
            operation_type=FileWriteOperationType.OVERWRITE,
            session_id=session_id,
        )
    )

    alerts = guard.get_alerts(session_id)
    assert len(alerts) == 2
    assert alerts[0].category == SensitiveFileCategory.PRIVATE_KEY
    assert alerts[1].category == SensitiveFileCategory.CLOUD_CREDENTIAL
