"""Immutable chained audit ledger engine for cross-system agent invocations.

[INPUT]
- Actor metadata, action types, resource targets, and input/output payload strings or bytes.

[OUTPUT]
- Cryptographically chained AuditLedgerRecord instances with tamper verification.

[POS]
- Harness core security ledger fulfilling HIPAA and SOC2 non-repudiation audit requirements.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Final

from myrm_agent_harness.core.security.zero_egress_provenance.types import (
    AuditLedgerRecord,
    AuditLedgerTamperError,
    EgressBoundaryState,
)

_GENESIS_HASH: Final[str] = "0" * 64


def _sha256_text(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class ImmutableAuditLedgerEngine:
    """Tamper-evident audit ledger using cryptographic hash chaining."""

    def __init__(self) -> None:
        self._records: list[AuditLedgerRecord] = []

    @property
    def record_count(self) -> int:
        """Total number of chained ledger records."""
        return len(self._records)

    def _compute_record_hash(
        self,
        record_id: str,
        seq: int,
        ts: str,
        actor: str,
        action: str,
        resource: str,
        inp_sha: str,
        out_sha: str,
        boundary: str,
        prev_hash: str,
    ) -> str:
        payload = f"{record_id}|{seq}|{ts}|{actor}|{action}|{resource}|{inp_sha}|{out_sha}|{boundary}|{prev_hash}"
        return _sha256_text(payload)

    def record_event(
        self,
        actor: str,
        action_type: str,
        resource_target: str,
        input_payload: str | bytes = "",
        output_payload: str | bytes = "",
        boundary_state: EgressBoundaryState = EgressBoundaryState.SANDBOX_CONFINED,
        timestamp_utc: str | None = None,
    ) -> AuditLedgerRecord:
        """Append an action entry to the immutable ledger, linking to the previous record hash."""
        seq = len(self._records)
        prev_hash = self._records[-1].current_record_hash if self._records else _GENESIS_HASH
        record_id = f"aud-{uuid.uuid4().hex[:12]}"
        ts = timestamp_utc or datetime.now(UTC).isoformat()
        inp_sha = _sha256_text(input_payload)
        out_sha = _sha256_text(output_payload)

        curr_hash = self._compute_record_hash(
            record_id=record_id,
            seq=seq,
            ts=ts,
            actor=actor,
            action=action_type,
            resource=resource_target,
            inp_sha=inp_sha,
            out_sha=out_sha,
            boundary=boundary_state.value,
            prev_hash=prev_hash,
        )

        record = AuditLedgerRecord(
            record_id=record_id,
            sequence_number=seq,
            timestamp_utc=ts,
            actor=actor,
            action_type=action_type,
            resource_target=resource_target,
            input_sha256=inp_sha,
            output_sha256=out_sha,
            boundary_state=boundary_state,
            previous_record_hash=prev_hash,
            current_record_hash=curr_hash,
        )
        self._records.append(record)
        return record

    def verify_chain_integrity(self, raise_on_error: bool = False) -> bool:
        """Recompute all hashes along the chain to guarantee no records were modified or deleted."""
        prev_hash = _GENESIS_HASH

        for idx, rec in enumerate(self._records):
            if rec.sequence_number != idx:
                if raise_on_error:
                    raise AuditLedgerTamperError(
                        f"Ledger sequence broke at index {idx}: recorded sequence {rec.sequence_number}."
                    )
                return False

            if rec.previous_record_hash != prev_hash:
                if raise_on_error:
                    raise AuditLedgerTamperError(
                        f"Ledger hash link broke at record '{rec.record_id}': expected previous {prev_hash}, got {rec.previous_record_hash}."
                    )
                return False

            expected_curr = self._compute_record_hash(
                record_id=rec.record_id,
                seq=rec.sequence_number,
                ts=rec.timestamp_utc,
                actor=rec.actor,
                action=rec.action_type,
                resource=rec.resource_target,
                inp_sha=rec.input_sha256,
                out_sha=rec.output_sha256,
                boundary=rec.boundary_state.value,
                prev_hash=rec.previous_record_hash,
            )

            if rec.current_record_hash != expected_curr:
                if raise_on_error:
                    raise AuditLedgerTamperError(
                        f"Tampered record detected at '{rec.record_id}': hash mismatch."
                    )
                return False

            prev_hash = rec.current_record_hash

        return True

    def export_ledger(self) -> tuple[AuditLedgerRecord, ...]:
        """Return full immutable sequence of audit ledger records."""
        return tuple(self._records)

    def get_record(self, record_id: str) -> AuditLedgerRecord | None:
        """Find a ledger record by ID."""
        for r in self._records:
            if r.record_id == record_id:
                return r
        return None
