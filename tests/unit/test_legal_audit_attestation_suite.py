import time

from myrm_agent_harness.core.security.legal_audit_attestation import (
    AuditEntryPayload,
    DigestAlgorithmEnum,
    EvidenceDossierSpec,
    LegalAuditAttestationSuite,
    MerkleAuditLedger,
    TsaAnchorGateway,
    VerificationStatusEnum,
)


def _make_sample_payload(action: str = "transfer_funds") -> AuditEntryPayload:
    return AuditEntryPayload(
        session_id="sess-test-001",
        actor_id="user-corp-ceo",
        agent_cert_id="cert-myrm-finance-v1",
        action_name=action,
        input_payload={"amount": "50000", "currency": "CNY", "to": "supplier-abc"},
        output_payload={"status": "approved", "tx_id": "tx-999"},
        metadata={"client_ip": "10.0.0.1"},
        timestamp=time.time(),
    )


def test_merkle_ledger_single_leaf_and_proof() -> None:
    ledger = MerkleAuditLedger()
    assert ledger.total_entries == 0
    empty_root = ledger.compute_root_hash()
    assert len(empty_root) == 64

    payload = _make_sample_payload()
    node = ledger.append_entry("entry-1", payload)
    assert ledger.total_entries == 1
    assert node.leaf_index == 0

    root = ledger.compute_root_hash()
    assert root == node.leaf_hash

    proof = ledger.generate_inclusion_proof(0)
    assert proof is not None
    assert proof.is_valid is True
    assert MerkleAuditLedger.verify_inclusion_proof(proof) is True


def test_merkle_ledger_multi_leaf_inclusion_proofs() -> None:
    ledger = MerkleAuditLedger()
    for i in range(5):
        payload = _make_sample_payload(f"action_{i}")
        ledger.append_entry(f"entry-{i}", payload)

    assert ledger.total_entries == 5
    root = ledger.compute_root_hash()

    for i in range(5):
        proof = ledger.generate_inclusion_proof(i)
        assert proof is not None
        assert proof.is_valid is True
        assert proof.root_hash == root
        assert MerkleAuditLedger.verify_inclusion_proof(proof) is True


def test_tsa_anchor_gateway_token_generation_and_verification() -> None:
    gateway = TsaAnchorGateway()
    digest = "a" * 64
    token = gateway.anchor_digest(digest, DigestAlgorithmEnum.SHA256)

    assert token.authority_id == TsaAnchorGateway.DEFAULT_AUTHORITY_ID
    assert token.digest == digest
    assert gateway.verify_timestamp_token(token) is True
    assert gateway.verify_timestamp_token(token, expected_digest=digest) is True
    assert gateway.verify_timestamp_token(token, expected_digest="b" * 64) is False


def test_evidence_dossier_full_workflow_and_verification() -> None:
    suite = LegalAuditAttestationSuite()
    payload = _make_sample_payload()
    suite.record_audit_event("entry-101", payload)

    dossier = suite.pack_evidence_dossier(
        entry_id="entry-101",
        approver_id="approver-compliance-officer",
        metadata={"jurisdiction": "PRC-Guiyang"},
    )
    assert dossier is not None
    assert dossier.approver_id == "approver-compliance-officer"

    verdict = suite.verify_evidence_dossier(dossier)
    assert verdict.is_valid is True
    assert verdict.status == VerificationStatusEnum.VALID
    assert verdict.leaf_match is True
    assert verdict.root_match is True
    assert verdict.tsa_match is True
    assert verdict.signature_match is True


def test_evidence_dossier_tampering_detection() -> None:
    suite = LegalAuditAttestationSuite()
    payload = _make_sample_payload()
    suite.record_audit_event("entry-202", payload)

    original_dossier = suite.pack_evidence_dossier("entry-202")
    assert original_dossier is not None

    # 1. Tamper leaf hash
    tampered_leaf = EvidenceDossierSpec(
        dossier_id=original_dossier.dossier_id,
        session_id=original_dossier.session_id,
        actor_id=original_dossier.actor_id,
        agent_cert_id=original_dossier.agent_cert_id,
        approver_id=original_dossier.approver_id,
        entry_id=original_dossier.entry_id,
        action_name=original_dossier.action_name,
        leaf_hash="f" * 64,  # tampered
        merkle_root=original_dossier.merkle_root,
        tsa_token=original_dossier.tsa_token,
        merkle_proof=original_dossier.merkle_proof,
        dossier_signature=original_dossier.dossier_signature,
        created_at=original_dossier.created_at,
    )
    verdict_tampered_leaf = suite.verify_evidence_dossier(tampered_leaf)
    assert verdict_tampered_leaf.is_valid is False
    assert verdict_tampered_leaf.status == VerificationStatusEnum.TAMPERED

    # 2. Tamper signature
    tampered_sig = EvidenceDossierSpec(
        dossier_id=original_dossier.dossier_id,
        session_id=original_dossier.session_id,
        actor_id=original_dossier.actor_id,
        agent_cert_id=original_dossier.agent_cert_id,
        approver_id=original_dossier.approver_id,
        entry_id=original_dossier.entry_id,
        action_name=original_dossier.action_name,
        leaf_hash=original_dossier.leaf_hash,
        merkle_root=original_dossier.merkle_root,
        tsa_token=original_dossier.tsa_token,
        merkle_proof=original_dossier.merkle_proof,
        dossier_signature="bad_signature_hex",
        created_at=original_dossier.created_at,
    )
    verdict_tampered_sig = suite.verify_evidence_dossier(tampered_sig)
    assert verdict_tampered_sig.is_valid is False
    assert verdict_tampered_sig.status == VerificationStatusEnum.SIGNATURE_INVALID
