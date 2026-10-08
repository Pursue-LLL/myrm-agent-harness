"""Handoff integrity sealing and signature verification pipeline for cross-agent task transfer.

[INPUT]
- toolkits.memory.cross_agent.types::HandoffPacket, HandoffVerificationResult, MemoryAssertion (POS: types)

[OUTPUT]
- HandoffIntegrityPipeline: Seals task handoff packets with SHA-256 signatures and verifies incoming payloads against tampering or corruption.

[POS]
Integrity verification pipeline preventing cross-agent context tampering, hallucination propagation, and stale state injection.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from myrm_agent_harness.toolkits.memory.cross_agent.types import (
    HandoffPacket,
    HandoffVerificationResult,
    MemoryAssertion,
)


def _serialize_canonical_assertions(assertions: list[MemoryAssertion]) -> str:
    """Serialize assertions deterministically for cryptographic hash generation."""
    sorted_items = sorted(
        assertions,
        key=lambda a: (a.subject.lower(), a.predicate.lower(), a.object_value.lower()),
    )
    tokens: list[str] = [
        f"{a.subject}:{a.predicate}:{a.object_value}:{a.confidence:.4f}:{a.source_agent_id}"
        for a in sorted_items
    ]
    return "|".join(tokens)


def _compute_handoff_signature(
    source_agent_id: str,
    target_agent_id: str,
    task_id: str,
    context_snapshot: str,
    assertions: list[MemoryAssertion],
    secret_salt: str = "",
) -> str:
    """Compute SHA-256 seal across sender, target, task, context, and canonical assertions."""
    canon_assertions = _serialize_canonical_assertions(assertions)
    payload = (
        f"{source_agent_id.strip()}::"
        f"{target_agent_id.strip()}::"
        f"{task_id.strip()}::"
        f"{context_snapshot.strip()}::"
        f"{canon_assertions}::"
        f"{secret_salt}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class HandoffIntegrityPipeline:
    """Cryptographic sealing and validation pipeline for multi-agent handoffs."""

    def __init__(self, secret_salt: str = "") -> None:
        self.secret_salt = secret_salt

    def seal_handoff(
        self,
        source_agent_id: str,
        target_agent_id: str,
        task_id: str,
        context_snapshot: str,
        assertions: list[MemoryAssertion] | None = None,
        secret_salt: str | None = None,
    ) -> HandoffPacket:
        """Create a sealed, tamper-evident handoff packet."""
        salt = self.secret_salt if secret_salt is None else secret_salt
        active_assertions = assertions or []
        packet_id = f"pkt-{uuid.uuid4().hex[:12]}"

        sig = _compute_handoff_signature(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            task_id=task_id,
            context_snapshot=context_snapshot,
            assertions=active_assertions,
            secret_salt=salt,
        )

        return HandoffPacket(
            packet_id=packet_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            task_id=task_id,
            context_snapshot=context_snapshot,
            critical_assertions=active_assertions,
            timestamp=time.time(),
            signature_sha256=sig,
        )

    def verify_handoff(
        self,
        packet: HandoffPacket,
        secret_salt: str | None = None,
    ) -> HandoffVerificationResult:
        """Verify the integrity seal of an incoming handoff packet."""
        salt = self.secret_salt if secret_salt is None else secret_salt

        expected_sig = _compute_handoff_signature(
            source_agent_id=packet.source_agent_id,
            target_agent_id=packet.target_agent_id,
            task_id=packet.task_id,
            context_snapshot=packet.context_snapshot,
            assertions=packet.critical_assertions,
            secret_salt=salt,
        )

        if packet.signature_sha256 != expected_sig:
            return HandoffVerificationResult(
                packet_id=packet.packet_id,
                is_valid=False,
                verified_assertions_count=0,
                rejection_reason=(
                    f"Signature mismatch: payload tampered or mismatched salt. "
                    f"Expected {expected_sig[:12]}..., got {packet.signature_sha256[:12]}..."
                ),
            )

        return HandoffVerificationResult(
            packet_id=packet.packet_id,
            is_valid=True,
            verified_assertions_count=len(packet.critical_assertions),
            rejection_reason=None,
        )
