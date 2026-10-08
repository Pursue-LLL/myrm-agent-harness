"""
[POS] tests/unit/test_media_artifact_role_scoped_grants_suite.py
[INPUT] myrm_agent_harness.core.security.media_artifact_grants
[OUTPUT] Unit tests for Media Artifact Role-Scoped Grants Suite

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.media_artifact_grants import (
    ArtifactGrantStatus,
    GrantEvaluationResult,
    MediaArtifactGrant,
    MediaArtifactRoleScopedGrantsFacade,
    ProducerRole,
)


def test_trusted_producer_roles_granted_inline_display() -> None:
    """Verify that assistant and tool generated media automatically receive inline presentation grant."""
    facade = MediaArtifactRoleScopedGrantsFacade()
    session_id = "session-chat-101"

    # 1. Assistant role: generated diagram artifact
    res_assistant: GrantEvaluationResult = facade.evaluate_and_grant(
        session_id=session_id,
        artifact_id="art-chart-svg-01",
        producer_role=ProducerRole.ASSISTANT,
        mime_type="image/svg+xml",
        checksum_sha256="sha256_mock_hash_svg",
        metadata={"title": "System Architecture Diagram"},
    )
    assert res_assistant.is_allowed is True
    assert res_assistant.grant_status == ArtifactGrantStatus.INLINE_RENDER_GRANTED
    assert res_assistant.rendered_preview_mode == "INLINE"

    # 2. Tool role: sandbox generated plot image
    res_tool: GrantEvaluationResult = facade.evaluate_and_grant(
        session_id=session_id,
        artifact_id="art-plot-png-02",
        producer_role=ProducerRole.TOOL,
        mime_type="image/png",
        checksum_sha256="sha256_mock_hash_png",
        metadata={"tool_name": "python_interpreter"},
    )
    assert res_tool.is_allowed is True
    assert res_tool.grant_status == ArtifactGrantStatus.INLINE_RENDER_GRANTED
    assert res_tool.rendered_preview_mode == "INLINE"

    # Verify query
    grant1 = facade.get_grant(session_id, "art-chart-svg-01")
    assert grant1 is not None
    assert grant1.producer_role == ProducerRole.ASSISTANT

    # Verify session list
    session_grants = facade.list_grants_for_session(session_id)
    assert len(session_grants) == 2


def test_untrusted_producer_roles_denied_automatic_inline() -> None:
    """Verify that user uploaded or external untrusted media cannot automatically render inline."""
    facade = MediaArtifactRoleScopedGrantsFacade()
    session_id = "session-chat-102"

    # 1. User submitted image (potential phishing or injection vector)
    res_user: GrantEvaluationResult = facade.evaluate_and_grant(
        session_id=session_id,
        artifact_id="art-user-upload-03",
        producer_role=ProducerRole.USER,
        mime_type="image/svg+xml",
        checksum_sha256="sha256_user_svg",
    )
    assert res_user.is_allowed is False
    assert res_user.grant_status == ArtifactGrantStatus.UNAUTHORIZED_EXTERNAL
    assert res_user.rendered_preview_mode == "SAFE_LINK_ONLY"
    assert "untrusted for automatic inline" in res_user.diagnostic_reason

    # 2. External untrusted webhook injected media
    res_ext: GrantEvaluationResult = facade.evaluate_and_grant(
        session_id=session_id,
        artifact_id="art-webhook-ext-04",
        producer_role=ProducerRole.EXTERNAL_UNTRUSTED,
        mime_type="text/html",
        checksum_sha256="sha256_webhook_html",
    )
    assert res_ext.is_allowed is False
    assert res_ext.grant_status == ArtifactGrantStatus.UNAUTHORIZED_EXTERNAL
    assert res_ext.rendered_preview_mode == "SAFE_LINK_ONLY"


def test_grant_revocation_and_cached_lookup() -> None:
    """Verify explicit grant revocation and consistent cached evaluation."""
    facade = MediaArtifactRoleScopedGrantsFacade()
    session_id = "session-chat-103"
    artifact_id = "art-report-pdf-05"

    # Initially grant to assistant
    res_init = facade.evaluate_and_grant(
        session_id=session_id,
        artifact_id=artifact_id,
        producer_role=ProducerRole.ASSISTANT,
        mime_type="application/pdf",
    )
    assert res_init.is_allowed is True

    # Revoke grant
    revoked = facade.revoke_grant(session_id, artifact_id, reason="Security audit flagged")
    assert revoked is True

    # Check stored record
    stored: MediaArtifactGrant | None = facade.get_grant(session_id, artifact_id)
    assert stored is not None
    assert stored.grant_status == ArtifactGrantStatus.REVOKED
    assert stored.is_inline_allowed is False

    # Second evaluation returns revoked status
    res_after = facade.evaluate_and_grant(
        session_id=session_id,
        artifact_id=artifact_id,
        producer_role=ProducerRole.ASSISTANT,
        mime_type="application/pdf",
    )
    assert res_after.is_allowed is False
    assert res_after.grant_status == ArtifactGrantStatus.REVOKED
    assert "explicitly revoked" in res_after.diagnostic_reason

    # Metrics check
    m = facade.metrics
    assert m.inline_granted_total >= 1
    assert m.grants_revoked_total >= 1
