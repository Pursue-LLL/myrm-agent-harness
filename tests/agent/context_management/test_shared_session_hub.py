# ============================================================================
# Unit Tests for SharedCloudSessionHub (Item 153)
# Verifies share token issuance, cryptographic verification, PII redaction,
# permission gates for inline annotations, and mid-flight steering injection.
# ============================================================================

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.agent.context_management.collaboration import (
    ShareAccessLevel,
    SharedCloudSessionHub,
)


def test_token_issuance_and_cryptographic_verification() -> None:
    """Verifies HMAC signature verification and expiration handling for share tokens."""
    hub = SharedCloudSessionHub(secret_salt="test-secret-salt-xyz")

    token = hub.issue_share_token(
        session_id="sess-dev-1",
        access_level=ShareAccessLevel.COMMENT_ONLY,
        duration_seconds=3600,
        created_by="alice",
    )

    assert token.session_id == "sess-dev-1"
    assert token.access_level == ShareAccessLevel.COMMENT_ONLY
    assert not token.is_expired()

    # Valid token verification
    valid, msg, retrieved = hub.verify_token(token.token_id)
    assert valid
    assert retrieved is not None
    assert retrieved.token_id == token.token_id

    # Expiration verification
    future_time = time.time() + 4000
    valid_exp, msg_exp, _ = hub.verify_token(token.token_id, current_time=future_time)
    assert not valid_exp
    assert "expired" in msg_exp

    # Non-existent token
    valid_fake, msg_fake, _ = hub.verify_token("stok-nonexistent")
    assert not valid_fake
    assert "not found" in msg_fake


def test_text_sanitization_privacy_protection() -> None:
    """Verifies that API keys, passwords, and local host directories are sanitized."""
    hub = SharedCloudSessionHub()

    raw_text = (
        "Here is the API key: sk-abcdef12345678901234567890 and Bearer eyJhbGciOiJIUzI1NiJ9.test\n"
        "Config file located at /Users/john_doe/secret_vault/db.json\n"
        "Database password: 'super_secret_password_123'"
    )

    sanitized, was_red = hub.sanitize_text(raw_text)

    assert was_red
    assert "sk-abcdef12345678901234567890" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert "/Users/john_doe" not in sanitized
    assert "/workspace/user/secret_vault/db.json" in sanitized
    assert "super_secret_password_123" not in sanitized


def test_generate_share_snapshot() -> None:
    """Verifies that snapshots are safely constructed with redacted transcript."""
    hub = SharedCloudSessionHub()
    raw_messages = [
        {
            "id": "msg-1",
            "role": "user",
            "content": "Please inspect my credentials in /Users/dev/key.pem",
        },
        {
            "id": "msg-2",
            "role": "assistant",
            "content": "I detected key sk-999999999999999999999999 in memory",
            "thought": "Internal key check: sk-888888888888888888888888",
        },
    ]

    snapshot = hub.generate_share_snapshot(
        session_id="session-arch",
        raw_messages=raw_messages,
        title="Architecture Design Review",
        access_level=ShareAccessLevel.READ_ONLY,
        public_artifact_ids=["art-arch-diagram"],
        duration_seconds=7200,
    )

    assert snapshot.title == "Architecture Design Review"
    assert snapshot.access_level == ShareAccessLevel.READ_ONLY
    assert len(snapshot.messages) == 2
    assert snapshot.messages[0].was_redacted
    assert "/workspace/user/key.pem" in snapshot.messages[0].content
    assert "[REDACTED_API_KEY]" in snapshot.messages[1].content
    assert "[REDACTED_API_KEY]" in snapshot.messages[1].thought_trace
    assert "art-arch-diagram" in snapshot.public_artifact_ids


def test_inline_annotation_permissions() -> None:
    """Verifies that READ_ONLY token cannot annotate while COMMENT_ONLY can."""
    hub = SharedCloudSessionHub()
    snapshot = hub.generate_share_snapshot(
        session_id="sess-annotate",
        raw_messages=[{"content": "hello"}],
        title="Session",
        access_level=ShareAccessLevel.COMMENT_ONLY,
    )

    token_ro = hub.issue_share_token("sess-annotate", ShareAccessLevel.READ_ONLY, created_by="guest")
    token_comment = hub.issue_share_token("sess-annotate", ShareAccessLevel.COMMENT_ONLY, created_by="bob")

    # READ_ONLY fails
    with pytest.raises(PermissionError):
        hub.add_inline_annotation(
            share_id=snapshot.share_id,
            token=token_ro,
            artifact_id="art-code",
            line_start=10,
            line_end=15,
            comment_text="Consider refactoring this loop",
        )

    # COMMENT_ONLY succeeds
    anno = hub.add_inline_annotation(
        share_id=snapshot.share_id,
        token=token_comment,
        artifact_id="art-code",
        line_start=10,
        line_end=15,
        comment_text="Consider refactoring this loop",
    )
    assert anno.author == "bob"
    assert anno.line_start == 10
    assert len(snapshot.annotations) == 1


def test_mid_flight_steering_injection_and_context_block() -> None:
    """Verifies that INTERACTIVE_STEERING can inject guidance and format context XML."""
    hub = SharedCloudSessionHub()
    token_comment = hub.issue_share_token("sess-steer", ShareAccessLevel.COMMENT_ONLY, created_by="reviewer")
    token_steer = hub.issue_share_token("sess-steer", ShareAccessLevel.INTERACTIVE_STEERING, created_by="tech_lead")

    # COMMENT_ONLY cannot steer
    with pytest.raises(PermissionError):
        hub.inject_steering_directive(
            session_id="sess-steer",
            token=token_comment,
            directive_text="Abort current path and use SQLite instead",
        )

    # INTERACTIVE_STEERING succeeds
    directive = hub.inject_steering_directive(
        session_id="sess-steer",
        token=token_steer,
        directive_text="Abort current path and use SQLite instead",
    )
    assert directive.author == "tech_lead"
    assert not directive.applied_to_context

    # Build steering context block
    block = hub.build_steering_context_block(session_id="sess-steer", consume=True)
    assert '<collaborative_team_steering priority="HIGH">' in block
    assert "@tech_lead" in block
    assert "Abort current path and use SQLite instead" in block

    # After consumption, block should be empty
    block_consumed = hub.build_steering_context_block(session_id="sess-steer", consume=True)
    assert block_consumed == ""


def test_collaboration_dataclass_serialization() -> None:
    """Verifies that serialization methods produce complete dictionary representations."""
    hub = SharedCloudSessionHub()
    token = hub.issue_share_token("sess-ser", ShareAccessLevel.READ_ONLY)
    t_dict = token.to_dict()
    assert t_dict["access_level"] == "read_only"
    assert t_dict["session_id"] == "sess-ser"

    snapshot = hub.generate_share_snapshot("sess-ser", [], "Title", ShareAccessLevel.READ_ONLY)
    s_dict = snapshot.to_dict()
    assert s_dict["title"] == "Title"
    assert s_dict["messages"] == []
