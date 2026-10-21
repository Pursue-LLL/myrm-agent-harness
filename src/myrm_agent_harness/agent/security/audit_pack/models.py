"""Data models for legal-grade audit pack and non-repudiation evidence dockets.

[POS]
Immutable contracts defining triad delegation proofs, cryptographic docket signatures,
and atomic legal audit dockets capturing the 5 golden evidence elements.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from myrm_agent_harness.agent.security.delegation.models import SubjectIdentity
from myrm_agent_harness.agent.security.jit_gate.models import AssetContentFingerprint


@dataclass(frozen=True, slots=True)
class TriadDelegationProof:
    """Legal representation of the three authoritative entities in an agent action."""

    initial_requester: SubjectIdentity
    executor_agent: SubjectIdentity
    business_approver: SubjectIdentity

    def to_dict(self) -> dict[str, object]:
        """Convert proof to serializable dictionary."""
        return {
            "initial_requester": self.initial_requester.to_dict(),
            "executor_agent": self.executor_agent.to_dict(),
            "business_approver": self.business_approver.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TriadDelegationProof:
        """Construct triad proof from dictionary."""
        return cls(
            initial_requester=SubjectIdentity.from_dict(dict(data.get("initial_requester", {}))),
            executor_agent=SubjectIdentity.from_dict(dict(data.get("executor_agent", {}))),
            business_approver=SubjectIdentity.from_dict(dict(data.get("business_approver", {}))),
        )


@dataclass(frozen=True, slots=True)
class DocketSignature:
    """Cryptographic seal attesting the non-repudiation and authenticity of an audit docket."""

    algorithm: str  # e.g., "HMAC-SHA256"
    key_id: str
    signature_value: str
    signed_at: float

    def to_dict(self) -> dict[str, object]:
        """Convert signature to dictionary."""
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "signature_value": self.signature_value,
            "signed_at": self.signed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DocketSignature:
        """Construct docket signature from dictionary."""
        return cls(
            algorithm=str(data.get("algorithm", "HMAC-SHA256")),
            key_id=str(data.get("key_id", "default")),
            signature_value=str(data.get("signature_value", "")),
            signed_at=float(data.get("signed_at", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class LegalAuditDocket:
    """Atomic, tamper-evident legal dossier bundling the 5 golden evidence elements."""

    docket_id: str
    action_type: str
    triad_proof: TriadDelegationProof
    input_summary: str
    output_summary: str
    asset_fingerprints: tuple[AssetContentFingerprint, ...]
    execution_receipt_hashes: tuple[str, ...]
    root_digest: str
    signature: DocketSignature | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_canonical_dict(self) -> dict[str, object]:
        """Generate canonical dictionary structure without signature for deterministic hashing."""
        return {
            "docket_id": self.docket_id,
            "action_type": self.action_type,
            "triad_proof": self.triad_proof.to_dict(),
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "asset_fingerprints": [fp.to_dict() for fp in self.asset_fingerprints],
            "execution_receipt_hashes": list(self.execution_receipt_hashes),
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    def to_canonical_json(self) -> str:
        """Serialize canonical dictionary to sorted, normalized JSON for root digest computation."""
        return json.dumps(self.to_canonical_dict(), sort_keys=True, separators=(",", ":"))

    def to_export_json_ld(self) -> str:
        """Export complete legal dossier in JSON-LD format with cryptographic signature seal."""
        doc = {
            "@context": "https://schema.org/AuditEvidenceRecord",
            "@type": "LegalAuditDocket",
            **self.to_canonical_dict(),
            "root_digest": self.root_digest,
            "signature": self.signature.to_dict() if self.signature else None,
        }
        return json.dumps(doc, indent=2, sort_keys=True)
