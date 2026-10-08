from dataclasses import dataclass, field
from enum import StrEnum


class DigestAlgorithmEnum(StrEnum):
    """Supported cryptographic hash digest algorithms."""

    SHA256 = "SHA-256"
    SHA384 = "SHA-384"
    SHA512 = "SHA-512"


class VerificationStatusEnum(StrEnum):
    """Verification outcome status for forensic audit dossiers."""

    VALID = "VALID"
    TAMPERED = "TAMPERED"
    ROOT_MISMATCH = "ROOT_MISMATCH"
    TSA_INVALID = "TSA_INVALID"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    CORRUPTED = "CORRUPTED"


@dataclass(frozen=True)
class AuditEntryPayload:
    """Raw payload of an agent execution event to be anchored in the ledger."""

    session_id: str
    actor_id: str
    agent_cert_id: str
    action_name: str
    input_payload: dict[str, str]
    output_payload: dict[str, str]
    metadata: dict[str, str]
    timestamp: float


@dataclass(frozen=True)
class MerkleAuditNode:
    """A leaf node in the Merkle audit ledger representing an attested action."""

    leaf_index: int
    entry_id: str
    leaf_hash: str
    timestamp: float
    details: dict[str, str]


@dataclass(frozen=True)
class MerkleProofStep:
    """A single step along the Merkle authentication path."""

    direction: str  # "left" or "right"
    hash_value: str


@dataclass(frozen=True)
class MerkleInclusionProof:
    """Cryptographic proof that a specific leaf exists in the Merkle tree root."""

    leaf_index: int
    leaf_hash: str
    root_hash: str
    audit_path: list[MerkleProofStep]
    is_valid: bool


@dataclass(frozen=True)
class TsaTimestampToken:
    """RFC 3161 compliant timestamp token issued by a trusted TSA."""

    token_id: str
    digest: str
    digest_algorithm: str
    timestamp_iso: str
    authority_id: str
    policy_oid: str
    serial_number: str
    signature_hex: str


@dataclass(frozen=True)
class EvidenceDossierSpec:
    """Self-contained legal-grade forensic evidence dossier for an attested action."""

    dossier_id: str
    session_id: str
    actor_id: str
    agent_cert_id: str
    approver_id: str | None
    entry_id: str
    action_name: str
    leaf_hash: str
    merkle_root: str
    tsa_token: TsaTimestampToken
    merkle_proof: MerkleInclusionProof
    dossier_signature: str
    created_at: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DossierVerificationResult:
    """Comprehensive forensic verification verdict on a legal evidence dossier."""

    is_valid: bool
    status: VerificationStatusEnum
    message: str
    leaf_match: bool
    root_match: bool
    tsa_match: bool
    signature_match: bool
