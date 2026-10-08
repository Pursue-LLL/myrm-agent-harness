"""Unit tests for Legal-Grade Audit Pack and Non-Repudiation Evidence Suite.

[POS]
Validates the atomic packaging of the 5 golden evidence elements, canonical root hashing,
HMAC-SHA256 non-repudiation signing, and offline standalone verification against tampering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from myrm_agent_harness.agent.security.audit_pack import (
    LegalAuditDocket,
    LegalAuditDocketBuilder,
    LegalAuditDocketVerifier,
    TriadDelegationProof,
)
from myrm_agent_harness.agent.security.delegation.models import (
    SubjectIdentity,
    SubjectType,
)
from myrm_agent_harness.agent.security.jit_gate.models import (
    AssetContentFingerprint,
    AssetType,
)


@pytest.fixture
def sample_triad_proof() -> TriadDelegationProof:
    """Fixture providing a verified triad delegation proof."""
    requester = SubjectIdentity(
        subject_id="user-corp-9988",
        subject_type=SubjectType.HUMAN,
        display_name="User Corp 9988",
        scopes=frozenset({"procurement_manager"}),
    )
    agent = SubjectIdentity(
        subject_id="agent-contract-drafter",
        subject_type=SubjectType.AGENT,
        display_name="Contract Drafter Agent",
        scopes=frozenset({"executor_agent"}),
    )
    approver = SubjectIdentity(
        subject_id="director-legal-001",
        subject_type=SubjectType.HUMAN,
        display_name="Director Legal 001",
        scopes=frozenset({"general_counsel"}),
    )
    return TriadDelegationProof(
        initial_requester=requester,
        executor_agent=agent,
        business_approver=approver,
    )


def test_docket_builder_seals_5_golden_evidence_elements(
    sample_triad_proof: TriadDelegationProof,
) -> None:
    """Ensure all 5 golden evidence elements are bundled and sealed with digital signature."""
    secret_key = "kms_secure_audit_pack_signing_key_2026"
    builder = LegalAuditDocketBuilder(
        action_type="FINANCIAL_CONTRACT_SIGNING",
        triad_proof=sample_triad_proof,
    )

    # Attach evidence elements
    builder.set_input_summary("Draft purchase agreement for Server Cluster #42, amount: $120,000")
    builder.set_output_summary("Contract signed and pushed to ERP, SHA256: e3b0c44298fc1c149...")

    fp = AssetContentFingerprint(
        asset_type=AssetType.FILE,
        asset_identifier="/workspace/contracts/cluster_42.pdf",
        content_sha256="a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
        st_size=48120,
        st_mtime_ns=1700000000123456789,
    )
    builder.add_asset_fingerprint(fp)
    builder.add_execution_receipt_hash("c7be1a8089b02a8b273a2fa8087595...receipt")
    builder.add_metadata("compliance_regulation", "SOX-404-AI-GOVERNANCE")

    docket = builder.build_and_seal(signing_secret=secret_key, key_id="kms-sox-key-01")

    # Verify structural integrity
    assert docket.docket_id.startswith("docket-")
    assert docket.action_type == "FINANCIAL_CONTRACT_SIGNING"
    assert docket.root_digest != ""
    assert docket.signature is not None
    assert docket.signature.algorithm == "HMAC-SHA256"
    assert docket.signature.key_id == "kms-sox-key-01"
    assert len(docket.asset_fingerprints) == 1
    assert len(docket.execution_receipt_hashes) == 1

    # Verify JSON-LD export schema
    json_ld = docket.to_export_json_ld()
    parsed = json.loads(json_ld)
    assert parsed["@context"] == "https://schema.org/AuditEvidenceRecord"
    assert parsed["@type"] == "LegalAuditDocket"
    assert parsed["root_digest"] == docket.root_digest
    assert parsed["signature"]["signature_value"] == docket.signature.signature_value


def test_docket_verifier_offline_success_and_tamper_detection(
    sample_triad_proof: TriadDelegationProof,
) -> None:
    """Ensure verifier passes on authentic docket, but rejects tampered content or invalid keys."""
    secret_key = "kms_top_secret_audit_key"
    builder = LegalAuditDocketBuilder(
        action_type="DEPLOY_PRODUCTION_DATABASE",
        triad_proof=sample_triad_proof,
    )
    builder.set_input_summary("Migrate schema v12 to v13")
    builder.set_output_summary("Migration successful: 42 tables altered")
    docket = builder.build_and_seal(signing_secret=secret_key)

    # 1. Authentic docket passes offline verification
    is_valid, err = LegalAuditDocketVerifier.verify_docket(docket, secret_key)
    assert is_valid is True
    assert err is None

    # 2. Wrong signing secret fails verification
    is_valid_wrong_key, err_key = LegalAuditDocketVerifier.verify_docket(docket, "wrong_secret")
    assert is_valid_wrong_key is False
    assert "Cryptographic signature seal verification failed" in (err_key or "")

    # 3. Content tampering detection (e.g., hacker altered input_summary in database)
    tampered_docket = LegalAuditDocket(
        docket_id=docket.docket_id,
        action_type=docket.action_type,
        triad_proof=docket.triad_proof,
        input_summary="Malicious drop database injection",  # Tampered!
        output_summary=docket.output_summary,
        asset_fingerprints=docket.asset_fingerprints,
        execution_receipt_hashes=docket.execution_receipt_hashes,
        root_digest=docket.root_digest,
        signature=docket.signature,
        created_at=docket.created_at,
        metadata=docket.metadata,
    )

    is_valid_tampered, err_tampered = LegalAuditDocketVerifier.verify_docket(tampered_docket, secret_key)
    assert is_valid_tampered is False
    assert "Root digest mismatch" in (err_tampered or "")
