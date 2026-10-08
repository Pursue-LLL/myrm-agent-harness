"""Immutable Append-Only Audit Ledger with SHA-256 Hash Chaining.

Provides cryptographic tamper-evidence, answering the connector invocation four questions:
1. Who invoked: user_id + agent_id
2. Which tool: tool_name
3. Which data source: connector_source + connector_scope
4. How recorded: authorized_parameters_hash + sanitized snapshot + reconcile_receipt
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from myrm_agent_harness.core.security.tripartite_ledger.types import (
    AuditEvidenceRecord,
    AuditIntegrityError,
    AuditLedgerVerificationResult,
    JsonScalar,
)

GENESIS_PREV_HASH = "0" * 64

SENSITIVE_KEY_SUBSTRINGS = (
    "secret",
    "password",
    "token",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "auth",
)


def sanitize_args_snapshot(args: Mapping[str, JsonScalar]) -> dict[str, JsonScalar]:
    """Sanitize arguments snapshot, stripping secrets and credentials."""
    sanitized: dict[str, JsonScalar] = {}
    for key, value in args.items():
        lower_key = key.lower()
        if any(substr in lower_key for substr in SENSITIVE_KEY_SUBSTRINGS):
            sanitized[key] = "[REDACTED_SECRET]"
        else:
            sanitized[key] = value
    return sanitized


def compute_canonical_hash(
    sequence_number: int,
    prev_hash: str,
    who_user_id: str,
    who_agent_id: str,
    when_timestamp: str,
    rule_version_hash: str,
    tool_name: str,
    tool_call_args_hash: str,
    sanitized_args_snapshot: dict[str, JsonScalar],
    connector_source: str,
    connector_scope: str,
    authorized_parameters_hash: str,
    reconcile_receipt: str,
) -> str:
    """Compute canonical SHA-256 hash for an audit record payload."""
    payload = {
        "sequence_number": sequence_number,
        "prev_hash": prev_hash,
        "who_user_id": who_user_id,
        "who_agent_id": who_agent_id,
        "when_timestamp": when_timestamp,
        "rule_version_hash": rule_version_hash,
        "tool_name": tool_name,
        "tool_call_args_hash": tool_call_args_hash,
        "sanitized_args_snapshot": sanitized_args_snapshot,
        "connector_source": connector_source,
        "connector_scope": connector_scope,
        "authorized_parameters_hash": authorized_parameters_hash,
        "reconcile_receipt": reconcile_receipt,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TripartiteAuditLedger:
    """Immutable Append-Only Audit Ledger with Cryptographic Hash Chaining."""

    def __init__(self) -> None:
        self._records: list[AuditEvidenceRecord] = []
        self._record_map: dict[str, AuditEvidenceRecord] = {}

    @property
    def record_count(self) -> int:
        """Total number of persisted immutable records."""
        return len(self._records)

    def append_record(
        self,
        who_user_id: str,
        who_agent_id: str,
        rule_version_hash: str,
        tool_name: str,
        tool_args: Mapping[str, JsonScalar],
        connector_source: str,
        connector_scope: str,
        authorized_parameters: Sequence[str],
        reconcile_receipt: str,
        record_id: str | None = None,
        when_timestamp: str | None = None,
    ) -> AuditEvidenceRecord:
        """Append an immutable audit evidence record to the ledger."""
        if not who_user_id or not who_agent_id:
            raise AuditIntegrityError("Both who_user_id and who_agent_id are required")
        if not connector_source or not connector_scope:
            raise AuditIntegrityError("Connector source and scope must be specified")

        seq = len(self._records)
        prev_hash = self._records[-1].record_hash if self._records else GENESIS_PREV_HASH
        rec_id = record_id or f"aud-{uuid.uuid4().hex[:12]}"
        ts = when_timestamp or datetime.now(UTC).isoformat()

        sanitized_args = sanitize_args_snapshot(tool_args)

        raw_args_bytes = json.dumps(tool_args, sort_keys=True, separators=(",", ":")).encode("utf-8")
        args_hash = hashlib.sha256(raw_args_bytes).hexdigest()

        param_bytes = json.dumps(sorted(authorized_parameters), separators=(",", ":")).encode("utf-8")
        param_hash = hashlib.sha256(param_bytes).hexdigest()

        rec_hash = compute_canonical_hash(
            sequence_number=seq,
            prev_hash=prev_hash,
            who_user_id=who_user_id,
            who_agent_id=who_agent_id,
            when_timestamp=ts,
            rule_version_hash=rule_version_hash,
            tool_name=tool_name,
            tool_call_args_hash=args_hash,
            sanitized_args_snapshot=sanitized_args,
            connector_source=connector_source,
            connector_scope=connector_scope,
            authorized_parameters_hash=param_hash,
            reconcile_receipt=reconcile_receipt,
        )

        record = AuditEvidenceRecord(
            record_id=rec_id,
            sequence_number=seq,
            prev_hash=prev_hash,
            record_hash=rec_hash,
            who_user_id=who_user_id,
            who_agent_id=who_agent_id,
            when_timestamp=ts,
            rule_version_hash=rule_version_hash,
            tool_name=tool_name,
            tool_call_args_hash=args_hash,
            sanitized_args_snapshot=sanitized_args,
            connector_source=connector_source,
            connector_scope=connector_scope,
            authorized_parameters_hash=param_hash,
            reconcile_receipt=reconcile_receipt,
        )

        self._records.append(record)
        self._record_map[rec_id] = record
        return record

    def verify_chain(self) -> AuditLedgerVerificationResult:
        """Verify the integrity of the cryptographic chain from genesis to head."""
        expected_prev = GENESIS_PREV_HASH

        for idx, rec in enumerate(self._records):
            if rec.sequence_number != idx:
                return AuditLedgerVerificationResult(
                    is_valid=False,
                    total_records=len(self._records),
                    corrupted_record_id=rec.record_id,
                    reason=f"Sequence number mismatch: expected {idx}, got {rec.sequence_number}",
                )

            if rec.prev_hash != expected_prev:
                return AuditLedgerVerificationResult(
                    is_valid=False,
                    total_records=len(self._records),
                    corrupted_record_id=rec.record_id,
                    reason=f"Previous hash broken at record {rec.record_id}",
                )

            recomputed_hash = compute_canonical_hash(
                sequence_number=rec.sequence_number,
                prev_hash=rec.prev_hash,
                who_user_id=rec.who_user_id,
                who_agent_id=rec.who_agent_id,
                when_timestamp=rec.when_timestamp,
                rule_version_hash=rec.rule_version_hash,
                tool_name=rec.tool_name,
                tool_call_args_hash=rec.tool_call_args_hash,
                sanitized_args_snapshot=rec.sanitized_args_snapshot,
                connector_source=rec.connector_source,
                connector_scope=rec.connector_scope,
                authorized_parameters_hash=rec.authorized_parameters_hash,
                reconcile_receipt=rec.reconcile_receipt,
            )

            if rec.record_hash != recomputed_hash:
                return AuditLedgerVerificationResult(
                    is_valid=False,
                    total_records=len(self._records),
                    corrupted_record_id=rec.record_id,
                    reason=f"Record hash payload tamper detected in record {rec.record_id}",
                )

            expected_prev = rec.record_hash

        return AuditLedgerVerificationResult(
            is_valid=True,
            total_records=len(self._records),
        )

    def query_records(
        self,
        connector_source: str | None = None,
        tool_name: str | None = None,
        who_agent_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[AuditEvidenceRecord]:
        """Query immutable audit records matching filter predicates."""
        matches: list[AuditEvidenceRecord] = []
        for rec in self._records:
            if connector_source and rec.connector_source != connector_source:
                continue
            if tool_name and rec.tool_name != tool_name:
                continue
            if who_agent_id and rec.who_agent_id != who_agent_id:
                continue
            if start_time and rec.when_timestamp < start_time:
                continue
            if end_time and rec.when_timestamp > end_time:
                continue
            matches.append(rec)
        return matches

    def get_record(self, record_id: str) -> AuditEvidenceRecord | None:
        """Fetch a record by its identifier."""
        return self._record_map.get(record_id)

    def has_record(self, record_id: str) -> bool:
        """Check if a record identifier exists in the ledger."""
        return record_id in self._record_map
