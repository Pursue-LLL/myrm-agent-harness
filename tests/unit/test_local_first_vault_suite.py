"""Unit tests for Local-First Zero-Leak Vault and Zero-Knowledge E2EE Sharing Gateway Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.local_first_vault import (
    DlpSensitivityCategory,
    TransparentDlpRedactionPipeline,
    VaultStorageMode,
    ZeroKnowledgeE2eeGateway,
)


def test_dlp_pipeline_sanitization() -> None:
    """Verify that DLP scanner detects and masks internal IPs, domains, secrets, phones, and pricing."""
    pipeline = TransparentDlpRedactionPipeline()
    sample_text = (
        "Internal server 192.168.1.50 hosted at api.internal.corp. "
        "Admin contact: 13800138000. Master key: sk_live_1234567890abcdef12345678. "
        "Total commercial quote: $250,000.00."
    )

    res = pipeline.sanitize_content(sample_text, enable_price_redaction=True)
    assert res.total_redactions == 5
    assert set(res.categories_found) == {
        DlpSensitivityCategory.INTERNAL_IP,
        DlpSensitivityCategory.INTERNAL_DOMAIN,
        DlpSensitivityCategory.PHONE_NUMBER,
        DlpSensitivityCategory.SECRET_TOKEN,
        DlpSensitivityCategory.COMMERCIAL_PRICE,
    }

    # Verify sensitive data is removed from output
    assert "192.168.1.50" not in res.sanitized_content
    assert "api.internal.corp" not in res.sanitized_content
    assert "13800138000" not in res.sanitized_content
    assert "sk_live_" not in res.sanitized_content
    assert "$250,000.00" not in res.sanitized_content

    # Verify masked placeholders
    assert "[INTERNAL_IP_MASKED]" in res.sanitized_content
    assert "[INTERNAL_DOMAIN_MASKED]" in res.sanitized_content
    assert "[PHONE_REDACTED]" in res.sanitized_content
    assert "[SECRET_TOKEN_REDACTED]" in res.sanitized_content
    assert "[CONFIDENTIAL_PRICE_REDACTED]" in res.sanitized_content


def test_local_vault_item_registration() -> None:
    """Verify physical local-first disk invariant (zero silent cloud sync)."""
    gateway = ZeroKnowledgeE2eeGateway()
    item = gateway.register_local_artifact(
        artifact_id="art_presentation_01",
        title="Q4 Commercial Proposal PPT",
        local_path="/mnt/volumes/user/ppt_deck.json",
        content='{"slides": ["Quarterly Targets", "Confidential Margins"]}',
        storage_mode=VaultStorageMode.LOCAL_FIRST_DISK,
    )

    assert item.artifact_id == "art_presentation_01"
    assert item.is_cloud_synced is False
    assert item.storage_mode == VaultStorageMode.LOCAL_FIRST_DISK
    assert len(item.content_hash) == 64

    # Lookup
    fetched = gateway.get_local_artifact("art_presentation_01")
    assert fetched == item
    assert len(gateway.list_local_artifacts()) == 1


def test_e2ee_share_envelope_creation_and_decryption() -> None:
    """Verify zero-knowledge AES-256-GCM envelope creation and client-side decryption."""
    gateway = ZeroKnowledgeE2eeGateway()
    sensitive_proposal = (
        "Enterprise Agreement with Acme Corp. "
        "Internal staging node: 10.240.0.12. "
        "Final contract value: $1,200,000.00."
    )

    # 1. Create E2EE envelope
    envelope, key = gateway.create_e2ee_share(
        artifact_id="art_proposal_02",
        plaintext_content=sensitive_proposal,
        ttl_seconds=3600,
        enable_dlp_sanitization=True,
    )
    assert envelope.dlp_audit_passed is True
    assert envelope.ciphertext_b64 is not None
    assert envelope.key_hash is not None

    # 2. Decrypt with valid key
    decrypted_text = gateway.decrypt_envelope(envelope.share_id, key)
    assert "Enterprise Agreement with Acme Corp." in decrypted_text
    # DLP sanitized before encryption
    assert "10.240.0.12" not in decrypted_text
    assert "[INTERNAL_IP_MASKED]" in decrypted_text
    assert "[CONFIDENTIAL_PRICE_REDACTED]" in decrypted_text

    # 3. Decrypt with invalid key
    wrong_key = b"0" * 32
    with pytest.raises(ValueError, match="does not match envelope proof"):
        gateway.decrypt_envelope(envelope.share_id, wrong_key)
