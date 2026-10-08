# [INPUT]: SchemaVersion, ShardAddress, ChatHeadPointer
# [OUTPUT]: compute_head_sha256, verify_lineage_cas, detect_head_fork
# [POS]: agent/context_management/chat_head_sync/chat_head_lineage_resolver.py

"""Lineage resolution and CAS identity chaining for chat head pointers.

[INPUT]
- SchemaVersion: Version tuple.
- ShardAddress: Shard content address.
- ChatHeadPointer: Chat head pointer.

[OUTPUT]
- compute_head_sha256: Canonical SHA-256 fingerprint computation for chat heads.
- verify_lineage_cas: Verification of parent lineage against current cloud head.
- detect_head_fork: Detection of causal divergence between two chat heads.

[POS]
Identity and ancestry verification engine guaranteeing CAS transitions and detecting forks.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

from .chat_head_types import ChatHeadPointer, SchemaVersion, ShardAddress


def compute_head_sha256(
    chat_id: str,
    schema_version: SchemaVersion,
    min_reader_version: SchemaVersion | None,
    parent_head_sha256: str | None,
    shard_addresses: Sequence[ShardAddress],
    metadata: Mapping[str, str],
) -> str:
    """Compute deterministic SHA-256 fingerprint for a chat head record.

    Continuity and ancestry are proven by cryptographic IDENTITY rather than
    sequence ordering. Two forked histories both number their turns sequentially,
    so sequence comparison would erroneously permit a split branch to overwrite
    the mainline.
    """
    canonical_dict = {
        "chat_id": chat_id,
        "schema_version": f"{schema_version.major}.{schema_version.minor}",
        "min_reader_version": (
            f"{min_reader_version.major}.{min_reader_version.minor}"
            if min_reader_version is not None
            else None
        ),
        "parent_head_sha256": parent_head_sha256,
        "shard_addresses": [
            {"sha256": addr.sha256, "byte_length": addr.byte_length}
            for addr in shard_addresses
        ],
        "metadata": dict(sorted(metadata.items())),
    }
    encoded = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_lineage_cas(
    current_head: ChatHeadPointer | None,
    expected_parent_sha256: str | None,
) -> tuple[bool, str | None]:
    """Verify CAS lineage before advancing the chat head pointer.

    Args:
        current_head: Currently persisted head pointer, or None if initial creation.
        expected_parent_sha256: Hash of the head that the new state claims to supersede.

    Returns:
        tuple[bool, str | None]: (is_valid, rejection_reason)
    """
    if current_head is None:
        if expected_parent_sha256 is not None:
            return (
                False,
                f"Initial head publication must have None parent, got '{expected_parent_sha256}'",
            )
        return True, None

    current_sha256 = current_head.head_sha256
    if expected_parent_sha256 != current_sha256:
        return (
            False,
            f"CAS collision: expected parent '{expected_parent_sha256}' does not match "
            f"current head '{current_sha256}'",
        )

    return True, None


def detect_head_fork(
    head_a: ChatHeadPointer,
    head_b: ChatHeadPointer,
    known_ancestors: Mapping[str, str | None],
) -> bool:
    """Detect whether two heads have diverged along separate ancestry lines.

    Args:
        head_a: First chat head pointer.
        head_b: Second chat head pointer.
        known_ancestors: Mapping of child_head_sha256 -> parent_head_sha256.

    Returns:
        bool: True if heads represent an unreconciled fork (neither is ancestor of the other).
    """
    if head_a.head_sha256 == head_b.head_sha256:
        return False

    def is_ancestor(potential_ancestor: str, start: str) -> bool:
        curr: str | None = start
        visited: set[str] = set()
        while curr is not None and curr not in visited:
            visited.add(curr)
            if curr == potential_ancestor:
                return True
            curr = known_ancestors.get(curr)
        return False

    a_is_ancestor_of_b = is_ancestor(head_a.head_sha256, head_b.head_sha256)
    b_is_ancestor_of_a = is_ancestor(head_b.head_sha256, head_a.head_sha256)

    # If neither is ancestor of the other, they are on divergent forked branches
    return not (a_is_ancestor_of_b or b_is_ancestor_of_a)
