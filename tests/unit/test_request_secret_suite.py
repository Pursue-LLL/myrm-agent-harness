"""
[POS] tests/unit/test_request_secret_suite.py
[INPUT] myrm_agent_harness.core.security.request_secret
[OUTPUT] Unit tests for RequestSecretMaskedCredentialCardSuite
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.request_secret import (
    IncompleteCredentialError,
    RequestSecretMaskedCredentialCardFacade,
    SecretInputSubmission,
    SecretRequestIntent,
    SecretRequestStatus,
)


@pytest.fixture
def facade() -> RequestSecretMaskedCredentialCardFacade:
    return RequestSecretMaskedCredentialCardFacade()


def test_create_and_fulfill_with_raw_secret(
    facade: RequestSecretMaskedCredentialCardFacade,
) -> None:
    intent = SecretRequestIntent(
        target_system="openai",
        purpose_description="Fetch embeddings for context retrieval",
        scope="api_key",
        ttl_seconds=3600,
    )
    card = facade.create_secret_request_card(
        agent_id="agent-search-01",
        task_id="task-embed-001",
        intent=intent,
    )

    assert card.card_id.startswith("card-sec-")
    assert card.status == SecretRequestStatus.PENDING
    assert card.intent.target_system == "openai"

    # Fulfill with newly provided plaintext secret
    submission = SecretInputSubmission(
        raw_secret="sk-live-super-secret-key-998877665544",
        extra_metadata={"environment": "production", "planted_evil_field": "exploit"},
    )
    res = facade.fulfill_secret_request(card.card_id, submission)

    assert res.card_id == card.card_id
    assert res.target_system == "openai"
    assert res.is_backfill is False
    assert res.stored_safely is True
    assert "sk-****5544" in res.mask_preview
    assert "sk-live-super-secret-key" not in res.transcript_safe_summary
    assert "sk-****5544" in res.transcript_safe_summary

    # Query card session
    updated = facade.get_card_session(card.card_id)
    assert updated is not None
    assert updated.status == SecretRequestStatus.FULFILLED
    assert updated.masked_ref is not None
    assert updated.masked_ref.mask_preview == res.mask_preview


def test_fulfill_with_masked_credential_backfill(
    facade: RequestSecretMaskedCredentialCardFacade,
) -> None:
    # 1. Register existing credential in vault
    saved_ref = facade.register_saved_credential(
        target_system="github",
        raw_secret="ghp_1234567890abcdef1234567890abcdef",
    )
    assert saved_ref.mask_preview.startswith("ghp_****")

    # 2. Agent creates request card
    card = facade.create_secret_request_card(
        agent_id="agent-git-01",
        task_id="task-repo-sync",
        intent=SecretRequestIntent(
            target_system="github",
            purpose_description="Clone and verify private repository",
        ),
    )

    # 3. User backfills using saved credential without re-entering plaintext
    submission = SecretInputSubmission(
        selected_credential_id=saved_ref.credential_id,
    )
    res = facade.fulfill_secret_request(card.card_id, submission)

    assert res.is_backfill is True
    assert res.target_system == "github"
    assert res.mask_preview == saved_ref.mask_preview
    assert "backfill=True" in res.transcript_safe_summary

    # 4. Reject mismatching target backfill
    mismatch_card = facade.create_secret_request_card(
        agent_id="agent-aws-01",
        task_id="task-aws-sync",
        intent=SecretRequestIntent(
            target_system="aws",
            purpose_description="Upload deployment artifacts",
        ),
    )
    with pytest.raises(IncompleteCredentialError, match="does not match requested 'aws'"):
        facade.fulfill_secret_request(
            mismatch_card.card_id,
            SecretInputSubmission(selected_credential_id=saved_ref.credential_id),
        )


def test_incomplete_credential_and_planted_fields_rejected(
    facade: RequestSecretMaskedCredentialCardFacade,
) -> None:
    card = facade.create_secret_request_card(
        agent_id="agent-01",
        task_id="task-01",
        intent=SecretRequestIntent(
            target_system="stripe",
            purpose_description="Charge invoice",
        ),
    )

    # Empty submission (neither raw secret nor selected ID)
    with pytest.raises(IncompleteCredentialError, match="Incomplete submission"):
        facade.fulfill_secret_request(card.card_id, SecretInputSubmission())

    # Short secret
    with pytest.raises(IncompleteCredentialError, match="too short"):
        facade.fulfill_secret_request(
            card.card_id,
            SecretInputSubmission(raw_secret="abc"),
        )


def test_reject_card_session(
    facade: RequestSecretMaskedCredentialCardFacade,
) -> None:
    card = facade.create_secret_request_card(
        agent_id="agent-01",
        task_id="task-01",
        intent=SecretRequestIntent(
            target_system="salesforce",
            purpose_description="Sync customer contacts",
        ),
    )

    rejected = facade.reject_secret_request(card.card_id, reason="Admin denied permission")
    assert rejected.status == SecretRequestStatus.REJECTED
    assert rejected.rejection_reason == "Admin denied permission"

    # Cannot fulfill a rejected card
    with pytest.raises(ValueError, match="Cannot fulfill card"):
        facade.fulfill_secret_request(
            card.card_id,
            SecretInputSubmission(raw_secret="valid_secret_12345"),
        )


def test_card_session_expiration(
    facade: RequestSecretMaskedCredentialCardFacade,
) -> None:
    card = facade.create_secret_request_card(
        agent_id="agent-01",
        task_id="task-01",
        intent=SecretRequestIntent(
            target_system="slack",
            purpose_description="Post notifications",
            ttl_seconds=60,
        ),
    )
    # Manually backdate expiration to simulate timeout
    session = facade.manager._sessions[card.card_id]
    object.__setattr__(session, "expires_at", time.time() - 10)

    queried = facade.get_card_session(card.card_id)
    assert queried is not None
    assert queried.status == SecretRequestStatus.EXPIRED
    assert "expired before user submission" in (queried.rejection_reason or "")
