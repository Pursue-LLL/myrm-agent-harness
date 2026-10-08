"""Unit tests for Enterprise Zero-Egress Audit Ledger & Asset Provenance Suite (Item 40).

[INPUT]
- ImmutableAuditLedgerEngine and GenerativeAssetProvenanceEngine.

[OUTPUT]
- Verified test outcomes ensuring non-repudiation hash chaining, tamper detection,
  and IP provenance dossier verification.

[POS]
- Harness core security test suite.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.zero_egress_provenance import (
    AttestationLevel,
    AuditLedgerRecord,
    AuditLedgerTamperError,
    EgressBoundaryState,
    GenerativeAssetProvenanceEngine,
    ImmutableAuditLedgerEngine,
    IPCleanlinessTier,
    ProvenanceVerificationError,
)


def test_immutable_audit_ledger_chaining_and_integrity() -> None:
    engine = ImmutableAuditLedgerEngine()

    # 1. Record series of cross-system events
    rec0 = engine.record_event(
        actor="agent-planner",
        action_type="DATABASE_QUERY",
        resource_target="tenant_db.users",
        input_payload="SELECT id FROM users",
        output_payload="[{'id': 1}]",
        boundary_state=EgressBoundaryState.SANDBOX_CONFINED,
    )
    assert rec0.sequence_number == 0
    assert rec0.previous_record_hash == "0" * 64

    rec1 = engine.record_event(
        actor="agent-coder",
        action_type="FILE_WRITE",
        resource_target="/workspace/model.py",
        input_payload="class Model: pass",
        output_payload="success",
        boundary_state=EgressBoundaryState.SANDBOX_CONFINED,
    )
    assert rec1.sequence_number == 1
    assert rec1.previous_record_hash == rec0.current_record_hash

    # 2. Verify integrity
    assert engine.verify_chain_integrity(raise_on_error=True) is True
    assert engine.record_count == 2
    assert len(engine.export_ledger()) == 2


def test_immutable_audit_ledger_tamper_detection() -> None:
    engine = ImmutableAuditLedgerEngine()
    engine.record_event(actor="actor1", action_type="READ", resource_target="res1")
    engine.record_event(actor="actor2", action_type="WRITE", resource_target="res2")

    # Manually tamper with a record
    tampered_rec = AuditLedgerRecord(
        record_id=engine._records[1].record_id,
        sequence_number=1,
        timestamp_utc=engine._records[1].timestamp_utc,
        actor="malicious_hacker",  # Changed actor
        action_type="TAMPERED_ACTION",
        resource_target="res2",
        input_sha256=engine._records[1].input_sha256,
        output_sha256=engine._records[1].output_sha256,
        boundary_state=EgressBoundaryState.SANDBOX_CONFINED,
        previous_record_hash=engine._records[1].previous_record_hash,
        current_record_hash=engine._records[1].current_record_hash,
    )
    engine._records[1] = tampered_rec

    assert engine.verify_chain_integrity(raise_on_error=False) is False
    with pytest.raises(AuditLedgerTamperError):
        engine.verify_chain_integrity(raise_on_error=True)


def test_generative_provenance_and_zero_egress_certificate() -> None:
    engine = GenerativeAssetProvenanceEngine(signing_secret="TEST_SECRET_2026")

    # 1. Zero-egress certificate
    cert = engine.generate_zero_egress_certificate(
        session_id="sess-enterprise-99",
        tenant_id="tenant-corp-1",
        sandbox_id="sbx-isolated-42",
        attestation_level=AttestationLevel.HIPAA_SOC2_CERTIFIED,
    )
    assert cert.zero_data_retention_guaranteed is True
    assert cert.no_model_training_guaranteed is True
    assert cert.attestation_level == AttestationLevel.HIPAA_SOC2_CERTIFIED
    assert len(cert.signature) == 64

    # 2. Generative asset provenance dossier
    code_content = "def calculate_risk(): return 0.0"
    prompt = "Write a python function to compute financial risk."
    dossier = engine.generate_provenance_dossier(
        asset_id="asset-fin-model",
        asset_name="risk_calculator.py",
        media_type="text/x-python",
        content=code_content,
        session_id="sess-enterprise-99",
        prompt_text=prompt,
        foundation_model_id="claude-3-7-sonnet",
        ip_tier=IPCleanlinessTier.ENTERPRISE_INDEMNIFIED,
    )
    assert dossier.ip_tier == IPCleanlinessTier.ENTERPRISE_INDEMNIFIED
    assert len(dossier.digital_signature) == 64

    # 3. Verify valid provenance
    assert engine.verify_asset_provenance(dossier, code_content) is True

    # 4. Verify tampered content fails
    tampered_code = "def calculate_risk(): return 999.0"
    assert engine.verify_asset_provenance(dossier, tampered_code) is False
    with pytest.raises(ProvenanceVerificationError):
        engine.verify_asset_provenance(dossier, tampered_code, raise_on_error=True)
