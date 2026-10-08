import hashlib
import json
import threading

from .types import (
    AuditEntryPayload,
    MerkleAuditNode,
    MerkleInclusionProof,
    MerkleProofStep,
)


def _hash_leaf(data: bytes) -> str:
    """RFC 6962 leaf node hash prefix: SHA-256(0x00 + data)."""
    hasher = hashlib.sha256()
    hasher.update(b"\x00")
    hasher.update(data)
    return hasher.hexdigest()


def _hash_internal(left_hex: str, right_hex: str) -> str:
    """RFC 6962 internal node hash prefix: SHA-256(0x01 + left + right)."""
    left_bytes = bytes.fromhex(left_hex)
    right_bytes = bytes.fromhex(right_hex)
    hasher = hashlib.sha256()
    hasher.update(b"\x01")
    hasher.update(left_bytes)
    hasher.update(right_bytes)
    return hasher.hexdigest()


class MerkleAuditLedger:
    """Thread-safe append-only cryptographic Merkle audit ledger."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leaves: list[MerkleAuditNode] = []

    @property
    def total_entries(self) -> int:
        """Total count of recorded audit entries."""
        with self._lock:
            return len(self._leaves)

    def append_entry(
        self,
        entry_id: str,
        payload: AuditEntryPayload,
    ) -> MerkleAuditNode:
        """Record an execution event as an immutable Merkle leaf node."""
        serialized = json.dumps(
            {
                "session_id": payload.session_id,
                "actor_id": payload.actor_id,
                "agent_cert_id": payload.agent_cert_id,
                "action_name": payload.action_name,
                "input_payload": payload.input_payload,
                "output_payload": payload.output_payload,
                "metadata": payload.metadata,
                "timestamp": payload.timestamp,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")

        leaf_hash = _hash_leaf(serialized)

        with self._lock:
            index = len(self._leaves)
            details_dict: dict[str, str] = {
                "session_id": payload.session_id,
                "actor_id": payload.actor_id,
                "agent_cert_id": payload.agent_cert_id,
                "action_name": payload.action_name,
            }
            node = MerkleAuditNode(
                leaf_index=index,
                entry_id=entry_id,
                leaf_hash=leaf_hash,
                timestamp=payload.timestamp,
                details=details_dict,
            )
            self._leaves.append(node)
            return node

    def get_leaf(self, index: int) -> MerkleAuditNode | None:
        """Retrieve a specific audit node by leaf index."""
        with self._lock:
            if 0 <= index < len(self._leaves):
                return self._leaves[index]
            return None

    def get_leaf_by_entry_id(self, entry_id: str) -> MerkleAuditNode | None:
        """Find an audit leaf node by unique entry id."""
        with self._lock:
            for leaf in self._leaves:
                if leaf.entry_id == entry_id:
                    return leaf
            return None

    def compute_root_hash(self) -> str:
        """Compute the current Merkle tree root hash across all recorded leaves."""
        with self._lock:
            hashes = [leaf.leaf_hash for leaf in self._leaves]

        if not hashes:
            # Empty tree SHA-256 digest
            return hashlib.sha256(b"").hexdigest()

        return self._compute_layer_root(hashes)

    @classmethod
    def _compute_layer_root(cls, current_level: list[str]) -> str:
        """Recursively calculate the root hash from bottom-level leaf hashes."""
        if not current_level:
            return hashlib.sha256(b"").hexdigest()
        if len(current_level) == 1:
            return current_level[0]

        next_level: list[str] = []
        i = 0
        while i < len(current_level):
            left = current_level[i]
            if i + 1 < len(current_level):
                right = current_level[i + 1]
            else:
                right = left  # Duplicate last element if odd number of nodes
            parent = _hash_internal(left, right)
            next_level.append(parent)
            i += 2

        return cls._compute_layer_root(next_level)

    def generate_inclusion_proof(
        self,
        leaf_index: int,
    ) -> MerkleInclusionProof | None:
        """Generate Merkle authentication path proving existence of a leaf."""
        with self._lock:
            if leaf_index < 0 or leaf_index >= len(self._leaves):
                return None

            leaf = self._leaves[leaf_index]
            current_hashes = [item.leaf_hash for item in self._leaves]

        root_hash = self.compute_root_hash()
        audit_path: list[MerkleProofStep] = []
        idx = leaf_index

        while len(current_hashes) > 1:
            next_layer: list[str] = []
            for i in range(0, len(current_hashes), 2):
                left = current_hashes[i]
                right = current_hashes[i + 1] if i + 1 < len(current_hashes) else left

                if i == (idx if idx % 2 == 0 else idx - 1):
                    if idx % 2 == 0:
                        audit_path.append(
                            MerkleProofStep(direction="right", hash_value=right)
                        )
                    else:
                        audit_path.append(
                            MerkleProofStep(direction="left", hash_value=left)
                        )

                next_layer.append(_hash_internal(left, right))

            idx = idx // 2
            current_hashes = next_layer

        valid = self.verify_inclusion_proof(
            MerkleInclusionProof(
                leaf_index=leaf_index,
                leaf_hash=leaf.leaf_hash,
                root_hash=root_hash,
                audit_path=audit_path,
                is_valid=True,
            )
        )

        return MerkleInclusionProof(
            leaf_index=leaf_index,
            leaf_hash=leaf.leaf_hash,
            root_hash=root_hash,
            audit_path=audit_path,
            is_valid=valid,
        )

    @staticmethod
    def verify_inclusion_proof(proof: MerkleInclusionProof) -> bool:
        """Verify if a Merkle inclusion proof mathematically matches the expected root."""
        current_hash = proof.leaf_hash

        for step in proof.audit_path:
            if step.direction == "right":
                current_hash = _hash_internal(current_hash, step.hash_value)
            elif step.direction == "left":
                current_hash = _hash_internal(step.hash_value, current_hash)
            else:
                return False

        return current_hash == proof.root_hash
