"""
[POS] src/myrm_agent_harness/core/security/ephemeral_identity_voucher/merkle_audit_ledger.py
[INPUT] hashlib, time, uuid, json, types
[OUTPUT] MerkleTreeAuditLedger

Cryptographic Merkle-Tree audit ledger providing non-repudiation and tamper-evident logs.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

from .types import (
    AuditEventRecord,
    AuditPhase,
    AuditProofBundle,
    EphemeralIdentityMetrics,
)


class MerkleTreeAuditLedger:
    """Maintains a tamper-evident cryptographically chained audit trail with Merkle root verification."""

    def __init__(self, metrics: EphemeralIdentityMetrics | None = None) -> None:
        # task_id -> list of sequentially chained audit event records
        self._task_events: dict[str, list[AuditEventRecord]] = {}
        self._metrics: EphemeralIdentityMetrics = (
            metrics if metrics is not None else EphemeralIdentityMetrics()
        )

    @property
    def metrics(self) -> EphemeralIdentityMetrics:
        """Operational metrics reference."""
        return self._metrics

    @staticmethod
    def _compute_sha256(data: str) -> str:
        """Compute standard hex SHA-256 hash."""
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_merkle_root(leaf_hashes: list[str]) -> str:
        """Compute the Merkle Root from an arbitrary ordered list of leaf hashes."""
        if not leaf_hashes:
            return hashlib.sha256(b"EMPTY_TREE").hexdigest()

        current_level: list[str] = list(leaf_hashes)

        while len(current_level) > 1:
            next_level: list[str] = []
            if len(current_level) % 2 != 0:
                current_level.append(current_level[-1])

            for i in range(0, len(current_level), 2):
                combined = current_level[i] + current_level[i + 1]
                parent_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
                next_level.append(parent_hash)

            current_level = next_level

        return current_level[0]

    def record_phase_event(
        self,
        task_id: str,
        phase: AuditPhase,
        summary: str,
        structured_payload: dict[str, str],
        timestamp_epoch: float | None = None,
    ) -> AuditEventRecord:
        """Append a cryptographically chained phase event for a task."""
        now = time.time() if timestamp_epoch is None else timestamp_epoch
        event_id = f"aud-{uuid.uuid4().hex[:12]}"

        # Canonical deterministic JSON stringification for payload hashing
        payload_str = json.dumps(structured_payload, sort_keys=True)
        payload_hash = self._compute_sha256(payload_str)

        history = self._task_events.setdefault(task_id, [])
        parent_hash = history[-1].node_hash if history else None

        # Chained node hash formula
        chain_basis = (
            f"{task_id}:{phase.value}:{now:.6f}:{payload_hash}:{parent_hash or 'GENESIS'}"
        )
        node_hash = self._compute_sha256(chain_basis)

        record = AuditEventRecord(
            event_id=event_id,
            task_id=task_id,
            phase=phase,
            timestamp_epoch=now,
            payload_hash=payload_hash,
            raw_summary=summary,
            parent_hash=parent_hash,
            node_hash=node_hash,
        )
        history.append(record)
        self._metrics.audit_events_recorded_total += 1
        return record

    def get_task_events(self, task_id: str) -> tuple[AuditEventRecord, ...]:
        """Return the immutable sequence of recorded events for a task."""
        return tuple(self._task_events.get(task_id, []))

    def verify_integrity(self, task_id: str) -> tuple[bool, str, str | None]:
        """Verify chain unbrokenness and compute active Merkle Root.

        Returns:
            Tuple of (is_valid, reason, computed_merkle_root_or_none).
        """
        events = self._task_events.get(task_id)
        if not events:
            empty_root = self.compute_merkle_root([])
            return True, "No events recorded for task (empty ledger)", empty_root

        expected_parent: str | None = None
        leaf_hashes: list[str] = []

        for idx, ev in enumerate(events):
            if ev.parent_hash != expected_parent:
                return (
                    False,
                    f"Chain corruption at event {idx} ({ev.event_id}): parent_hash mismatch",
                    None,
                )

            chain_basis = (
                f"{ev.task_id}:{ev.phase.value}:{ev.timestamp_epoch:.6f}:"
                f"{ev.payload_hash}:{ev.parent_hash or 'GENESIS'}"
            )
            recalculated_node_hash = self._compute_sha256(chain_basis)
            if recalculated_node_hash != ev.node_hash:
                return (
                    False,
                    f"Hash integrity violated at event {idx} ({ev.event_id}): recalculated hash differs",
                    None,
                )

            leaf_hashes.append(ev.node_hash)
            expected_parent = ev.node_hash

        merkle_root = self.compute_merkle_root(leaf_hashes)
        return True, "All audit event nodes cryptographically verified", merkle_root

    def export_proof_bundle(self, task_id: str) -> AuditProofBundle:
        """Export verifiable cryptographic proof bundle for compliance audits."""
        events = tuple(self._task_events.get(task_id, []))
        is_valid, _reason, merkle_root = self.verify_integrity(task_id)
        root = merkle_root if merkle_root is not None else self.compute_merkle_root([])

        phases_set: list[str] = []
        for ev in events:
            if ev.phase.value not in phases_set:
                phases_set.append(ev.phase.value)

        return AuditProofBundle(
            task_id=task_id,
            merkle_root=root,
            phases_included=tuple(phases_set),
            events=events,
            verification_success=is_valid,
            exported_at_epoch=time.time(),
        )
