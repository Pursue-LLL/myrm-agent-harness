import hashlib
import hmac
import time
import uuid

from .merkle_ledger import MerkleAuditLedger
from .tsa_anchor_gateway import TsaAnchorGateway
from .types import (
    AuditEntryPayload,
    DigestAlgorithmEnum,
    DossierVerificationResult,
    EvidenceDossierSpec,
    MerkleAuditNode,
    TsaTimestampToken,
    VerificationStatusEnum,
)


class EvidenceDossierPacker:
    """Packs cryptographic audit records and TSA tokens into legal evidence dossiers."""

    def __init__(self, enterprise_signing_key: str = "MYRM_ENTERPRISE_CA_SIGNING_KEY_2026") -> None:
        self._signing_key = enterprise_signing_key.encode("utf-8")

    def pack_dossier(
        self,
        session_id: str,
        actor_id: str,
        agent_cert_id: str,
        approver_id: str | None,
        entry_id: str,
        action_name: str,
        leaf_hash: str,
        merkle_root: str,
        tsa_token: TsaTimestampToken,
        merkle_proof: "MerkleInclusionProof",  # type: ignore # noqa: F821
        metadata: dict[str, str] | None = None,
    ) -> EvidenceDossierSpec:
        """Create a cryptographically signed legal evidence dossier."""
        dossier_id = f"dos-{uuid.uuid4().hex[:12]}"
        now = time.time()
        meta = metadata if metadata is not None else {}

        material = (
            f"{dossier_id}|{session_id}|{actor_id}|{agent_cert_id}|"
            f"{approver_id or ''}|{entry_id}|{action_name}|{leaf_hash}|"
            f"{merkle_root}|{tsa_token.signature_hex}|{merkle_proof.root_hash}"
        )
        dossier_sig = hmac.new(
            self._signing_key,
            material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return EvidenceDossierSpec(
            dossier_id=dossier_id,
            session_id=session_id,
            actor_id=actor_id,
            agent_cert_id=agent_cert_id,
            approver_id=approver_id,
            entry_id=entry_id,
            action_name=action_name,
            leaf_hash=leaf_hash,
            merkle_root=merkle_root,
            tsa_token=tsa_token,
            merkle_proof=merkle_proof,
            dossier_signature=dossier_sig,
            created_at=now,
            metadata=meta,
        )

    def verify_dossier_signature(self, dossier: EvidenceDossierSpec) -> bool:
        """Verify the cryptographic signature on the dossier itself."""
        material = (
            f"{dossier.dossier_id}|{dossier.session_id}|{dossier.actor_id}|"
            f"{dossier.agent_cert_id}|{dossier.approver_id or ''}|"
            f"{dossier.entry_id}|{dossier.action_name}|{dossier.leaf_hash}|"
            f"{dossier.merkle_root}|{dossier.tsa_token.signature_hex}|"
            f"{dossier.merkle_proof.root_hash}"
        )
        expected_sig = hmac.new(
            self._signing_key,
            material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(dossier.dossier_signature, expected_sig)


class EvidenceDossierVerifier:
    """Verifies legal-grade anti-repudiation evidence dossiers against mathematical proofs."""

    def __init__(
        self,
        packer: EvidenceDossierPacker,
        tsa_gateway: TsaAnchorGateway,
    ) -> None:
        self._packer = packer
        self._tsa_gateway = tsa_gateway

    def verify_dossier(self, dossier: EvidenceDossierSpec) -> DossierVerificationResult:
        """Perform comprehensive forensic verification of the evidence dossier."""
        # 1. Check leaf hash consistency
        leaf_match = dossier.leaf_hash == dossier.merkle_proof.leaf_hash
        if not leaf_match:
            return DossierVerificationResult(
                is_valid=False,
                status=VerificationStatusEnum.TAMPERED,
                message="Leaf hash mismatch between dossier and inclusion proof",
                leaf_match=False,
                root_match=False,
                tsa_match=False,
                signature_match=False,
            )

        # 2. Check Merkle root consistency and inclusion proof validity
        root_valid = (
            dossier.merkle_root == dossier.merkle_proof.root_hash
            and MerkleAuditLedger.verify_inclusion_proof(dossier.merkle_proof)
        )
        if not root_valid:
            return DossierVerificationResult(
                is_valid=False,
                status=VerificationStatusEnum.ROOT_MISMATCH,
                message="Merkle root mismatch or invalid mathematical inclusion path",
                leaf_match=True,
                root_match=False,
                tsa_match=False,
                signature_match=False,
            )

        # 3. Check TSA token validity (Token must anchor root or leaf and have valid TSA signature)
        tsa_digest_matches = (
            dossier.tsa_token.digest == dossier.merkle_root
            or dossier.tsa_token.digest == dossier.leaf_hash
        )
        tsa_sig_valid = self._tsa_gateway.verify_timestamp_token(dossier.tsa_token)
        tsa_match = tsa_digest_matches and tsa_sig_valid

        if not tsa_match:
            return DossierVerificationResult(
                is_valid=False,
                status=VerificationStatusEnum.TSA_INVALID,
                message="TSA timestamp token is invalid, forged, or digest does not match root",
                leaf_match=True,
                root_match=True,
                tsa_match=False,
                signature_match=False,
            )

        # 4. Check Dossier signature
        signature_match = self._packer.verify_dossier_signature(dossier)
        if not signature_match:
            return DossierVerificationResult(
                is_valid=False,
                status=VerificationStatusEnum.SIGNATURE_INVALID,
                message="Dossier cryptographic seal has been tampered with or corrupted",
                leaf_match=True,
                root_match=True,
                tsa_match=True,
                signature_match=False,
            )

        return DossierVerificationResult(
            is_valid=True,
            status=VerificationStatusEnum.VALID,
            message="Evidence dossier mathematically intact and verified against RFC 3161 TSA",
            leaf_match=True,
            root_match=True,
            tsa_match=True,
            signature_match=True,
        )


class LegalAuditAttestationSuite:
    """Unified facade for legal-grade cryptographic audit, TSA anchoring, and non-repudiation."""

    def __init__(
        self,
        enterprise_signing_key: str = "MYRM_ENTERPRISE_CA_SIGNING_KEY_2026",
        tsa_authority_id: str = TsaAnchorGateway.DEFAULT_AUTHORITY_ID,
    ) -> None:
        self.ledger = MerkleAuditLedger()
        self.tsa_gateway = TsaAnchorGateway(authority_id=tsa_authority_id)
        self.packer = EvidenceDossierPacker(enterprise_signing_key=enterprise_signing_key)
        self.verifier = EvidenceDossierVerifier(self.packer, self.tsa_gateway)

    def record_audit_event(
        self,
        entry_id: str,
        payload: AuditEntryPayload,
    ) -> MerkleAuditNode:
        """Record an execution event in the immutable Merkle ledger."""
        return self.ledger.append_entry(entry_id=entry_id, payload=payload)

    def anchor_merkle_root(
        self,
        digest_algorithm: DigestAlgorithmEnum = DigestAlgorithmEnum.SHA256,
    ) -> TsaTimestampToken:
        """Issue an RFC 3161 timestamp token anchoring the current Merkle root."""
        root_hash = self.ledger.compute_root_hash()
        return self.tsa_gateway.anchor_digest(
            digest=root_hash,
            digest_algorithm=digest_algorithm,
        )

    def pack_evidence_dossier(
        self,
        entry_id: str,
        approver_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> EvidenceDossierSpec | None:
        """Pack an existing audit entry into an attested legal dossier."""
        leaf = self.ledger.get_leaf_by_entry_id(entry_id)
        if leaf is None:
            return None

        proof = self.ledger.generate_inclusion_proof(leaf.leaf_index)
        if proof is None:
            return None

        # Anchor current root to TSA
        root_hash = self.ledger.compute_root_hash()
        tsa_token = self.tsa_gateway.anchor_digest(root_hash)

        return self.packer.pack_dossier(
            session_id=leaf.details.get("session_id", ""),
            actor_id=leaf.details.get("actor_id", ""),
            agent_cert_id=leaf.details.get("agent_cert_id", ""),
            approver_id=approver_id,
            entry_id=entry_id,
            action_name=leaf.details.get("action_name", ""),
            leaf_hash=leaf.leaf_hash,
            merkle_root=root_hash,
            tsa_token=tsa_token,
            merkle_proof=proof,
            metadata=metadata,
        )

    def verify_evidence_dossier(
        self,
        dossier: EvidenceDossierSpec,
    ) -> DossierVerificationResult:
        """Verify an evidence dossier."""
        return self.verifier.verify_dossier(dossier)
