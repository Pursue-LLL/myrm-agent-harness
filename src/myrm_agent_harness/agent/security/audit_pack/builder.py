"""Builder for assembling and cryptographically sealing legal audit dockets.

[POS]
Aggregates the 5 golden evidence elements, computes the canonical root digest,
and signs the docket with HMAC-SHA256 non-repudiation signature.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from uuid import uuid4

from myrm_agent_harness.agent.security.audit_pack.models import (
    DocketSignature,
    LegalAuditDocket,
    TriadDelegationProof,
)
from myrm_agent_harness.agent.security.jit_gate.models import AssetContentFingerprint


class LegalAuditDocketBuilder:
    """Builder for constructing tamper-evident LegalAuditDocket dossiers."""

    def __init__(self, action_type: str, triad_proof: TriadDelegationProof) -> None:
        self._docket_id: str = f"docket-{uuid4().hex[:12]}"
        self._action_type: str = action_type
        self._triad_proof: TriadDelegationProof = triad_proof
        self._input_summary: str = ""
        self._output_summary: str = ""
        self._asset_fingerprints: list[AssetContentFingerprint] = []
        self._receipt_hashes: list[str] = []
        self._metadata: dict[str, str] = {}
        self._created_at: float = time.time()

    def set_input_summary(self, summary: str) -> LegalAuditDocketBuilder:
        """Record canonicalized input summary or prompt parameters."""
        self._input_summary = summary
        return self

    def set_output_summary(self, summary: str) -> LegalAuditDocketBuilder:
        """Record action output delivery summary or outcome status."""
        self._output_summary = summary
        return self

    def add_asset_fingerprint(self, fingerprint: AssetContentFingerprint) -> LegalAuditDocketBuilder:
        """Attach physical asset sha256 fingerprint involved in this action."""
        self._asset_fingerprints.append(fingerprint)
        return self

    def add_execution_receipt_hash(self, receipt_hash: str) -> LegalAuditDocketBuilder:
        """Link immutable execution receipt hash from audit ledger."""
        self._receipt_hashes.append(receipt_hash)
        return self

    def add_metadata(self, key: str, value: str) -> LegalAuditDocketBuilder:
        """Attach governance metadata key-value pair."""
        self._metadata[key] = value
        return self

    def build_and_seal(self, signing_secret: str, key_id: str = "sys-kms-01") -> LegalAuditDocket:
        """Compute canonical root digest, sign docket, and seal into immutable dossier."""
        docket_stub = LegalAuditDocket(
            docket_id=self._docket_id,
            action_type=self._action_type,
            triad_proof=self._triad_proof,
            input_summary=self._input_summary,
            output_summary=self._output_summary,
            asset_fingerprints=tuple(self._asset_fingerprints),
            execution_receipt_hashes=tuple(self._receipt_hashes),
            root_digest="",
            signature=None,
            created_at=self._created_at,
            metadata=dict(self._metadata),
        )

        # 1. Compute canonical root digest over all 5 golden evidence elements
        canonical_json = docket_stub.to_canonical_json()
        root_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        # 2. Cryptographic signature seal over root digest
        sig_bytes = hmac.new(
            signing_secret.encode("utf-8"),
            root_digest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signature = DocketSignature(
            algorithm="HMAC-SHA256",
            key_id=key_id,
            signature_value=sig_bytes,
            signed_at=time.time(),
        )

        # 3. Return sealed docket
        return LegalAuditDocket(
            docket_id=docket_stub.docket_id,
            action_type=docket_stub.action_type,
            triad_proof=docket_stub.triad_proof,
            input_summary=docket_stub.input_summary,
            output_summary=docket_stub.output_summary,
            asset_fingerprints=docket_stub.asset_fingerprints,
            execution_receipt_hashes=docket_stub.execution_receipt_hashes,
            root_digest=root_digest,
            signature=signature,
            created_at=docket_stub.created_at,
            metadata=docket_stub.metadata,
        )
