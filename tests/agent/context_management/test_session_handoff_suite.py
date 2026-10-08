"""Unit tests for SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    HandoffMessageTurn,
    SecretSeverity,
    SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite,
    ShareAccessStatus,
)


def test_handoff_package_creation_and_restoration_with_storage_masking() -> None:
    """Test packaging session with storage secret masking and subsequent package restoration."""
    suite = SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite()

    turns = [
        HandoffMessageTurn(
            turn_id=1,
            role="user",
            content="Please query the analytics DB with api key sk-live-secret-openai-key-998877665544332211",
        ),
        HandoffMessageTurn(
            turn_id=2,
            role="assistant",
            content="I executed query using token Bearer 1234567890abcdef1234567890abcdef and generated chart.",
            tool_calls_summary="db_query(limit=10)",
            artifacts_generated=["chart_q3.png"],
        ),
    ]
    env_vars = {"DATABASE_URL": "postgresql://usr:secret_pass@localhost:5432/db", "SERVICE_PORT": "8080"}

    package = suite.create_handoff_package(
        session_id="session-ops-001",
        creator_id="alice",
        topic_summary="Q3 Analytics Pipeline",
        turns=turns,
        env_vars=env_vars,
        auto_mask_secrets=True,
    )

    assert package.session_id == "session-ops-001"
    assert package.creator_id == "alice"
    assert package.topic_summary == "Q3 Analytics Pipeline"
    assert len(package.turns) == 2

    # Storage masking verification
    assert "sk-live-secret-openai-key" not in package.turns[0].content
    assert "<REDACTED_SECRET:OPENAI_API_KEY>" in package.turns[0].content
    assert "<REDACTED_SECRET:GENERIC_BEARER>" in package.turns[1].content

    # Restoration verification
    restored = suite.restore_handoff_package(package.package_id)
    assert restored.package_id == package.package_id
    assert restored.manifest_hash == package.manifest_hash
    assert restored.turns[1].artifacts_generated == ["chart_q3.png"]


def test_readonly_share_grants_access_and_audit_limits() -> None:
    """Test readonly share grant issuing, password verification, view quotas, and revocation."""
    suite = SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite()

    turns = [HandoffMessageTurn(turn_id=1, role="user", content="Hello world")]
    package = suite.create_handoff_package(
        session_id="session-demo-02",
        creator_id="bob",
        topic_summary="General Greeting",
        turns=turns,
    )

    # Issue grant with password and max 2 views
    grant = suite.create_readonly_share_grant(
        package_id=package.package_id,
        ttl_seconds=3600,
        max_views=2,
        password="secure-share-password",
    )

    # 1. Access without password
    status, pkg = suite.access_readonly_share(grant.share_url_token)
    assert status == ShareAccessStatus.PASSWORD_REQUIRED
    assert pkg is None

    # 2. Access with wrong password
    status, pkg = suite.access_readonly_share(grant.share_url_token, password_attempt="wrong-pwd")
    assert status == ShareAccessStatus.INVALID_PASSWORD
    assert pkg is None

    # 3. Access with correct password (View 1)
    status, pkg = suite.access_readonly_share(grant.share_url_token, password_attempt="secure-share-password")
    assert status == ShareAccessStatus.GRANTED
    assert pkg is not None
    assert pkg.package_id == package.package_id

    # 4. Access with correct password (View 2)
    status, pkg = suite.access_readonly_share(grant.share_url_token, password_attempt="secure-share-password")
    assert status == ShareAccessStatus.GRANTED
    assert pkg is not None

    # 5. Access exceeding quota (View 3)
    status, pkg = suite.access_readonly_share(grant.share_url_token, password_attempt="secure-share-password")
    assert status == ShareAccessStatus.QUOTA_EXCEEDED
    assert pkg is None

    # 6. Revocation test
    new_grant = suite.create_readonly_share_grant(package_id=package.package_id, ttl_seconds=600, max_views=5)
    suite.revoke_readonly_share(new_grant.grant_id)
    status, _ = suite.access_readonly_share(new_grant.share_url_token)
    assert status == ShareAccessStatus.REVOKED


def test_secret_gate_pre_publish_blocking() -> None:
    """Test Tier 2 pre-publish scanner blocking when raw unmasked secrets are present."""
    suite = SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite()

    leaked_turn = HandoffMessageTurn(
        turn_id=1,
        role="assistant",
        content="Here is your key: sk-ant-secret-openai-leak-1234567890abcdef12345",
    )

    # When auto_mask_secrets is False, pre-publish gate strictly blocks with PermissionError
    with pytest.raises(PermissionError) as exc_info:
        suite.create_handoff_package(
            session_id="session-leak-03",
            creator_id="charlie",
            topic_summary="Critical Leak Test",
            turns=[leaked_turn],
            auto_mask_secrets=False,
        )

    assert "Handoff packaging blocked by secret gate" in str(exc_info.value)

    # Standalone scanner inspection
    scan_result = suite.scanner.scan_for_release_gate(
        texts=[leaked_turn.content],
        env_vars={"GITHUB_TOKEN": "ghp_1234567890abcdefghijklmnopqrstuvwxyz"},
    )
    assert scan_result.passed is False
    assert scan_result.critical_findings_count >= 1
    assert any(f.severity == SecretSeverity.CRITICAL for f in scan_result.findings)


def test_session_blame_indexer_and_line_provenance() -> None:
    """Test recording and querying line-level reverse provenance to session turns."""
    suite = SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite()

    file_path = "src/core/auth_handler.py"

    # Record turn 1 generating lines 10-25
    suite.record_line_blame(
        file_path=file_path,
        start_line=10,
        end_line=25,
        session_id="sess-auth-dev",
        turn_id=3,
        prompt_intent="Implement OAuth2 token verification function",
        timestamp_iso="2026-10-08T08:00:00Z",
    )

    # Record turn 2 modifying lines 20-30 (overlapping)
    suite.record_line_blame(
        file_path=file_path,
        start_line=20,
        end_line=30,
        session_id="sess-auth-dev",
        turn_id=5,
        prompt_intent="Add audience and issuer validation to token check",
        timestamp_iso="2026-10-08T08:05:00Z",
    )

    # Line 15 belongs to turn 3
    lookup_15 = suite.blame_code_line(file_path=file_path, line_number=15)
    assert lookup_15.found is True
    assert lookup_15.entry is not None
    assert lookup_15.entry.turn_id == 3

    # Line 22 was touched by turn 5 (most recent wins)
    lookup_22 = suite.blame_code_line(file_path=file_path, line_number=22)
    assert lookup_22.found is True
    assert lookup_22.entry is not None
    assert lookup_22.entry.turn_id == 5

    # Line 50 is outside recorded ranges
    lookup_50 = suite.blame_code_line(file_path=file_path, line_number=50)
    assert lookup_50.found is False
    assert lookup_50.entry is None
