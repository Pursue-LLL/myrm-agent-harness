"""
[POS] src/myrm_agent_harness/core/security/air_gapped_sovereignty/evidentiary_archive_packer.py
[INPUT] json, time, uuid, typing, .gm_crypto_engine (sm3_hash), .types (AuditBundleRecord)
[OUTPUT] EvidentiaryArchivePacker

Packages and seals air-gapped agent operations and decision logs into tamper-evident
audit bundles with cryptographic SM3 Merkle root digest verification.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import json
import time
import uuid

from .gm_crypto_engine import sm3_hash
from .types import AuditBundleRecord


class EvidentiaryArchivePacker:
    """Creates and verifies tamper-evident, air-gapped cryptographic evidentiary bundles."""

    @classmethod
    def calculate_record_sm3(cls, record: dict[str, str]) -> str:
        """Compute deterministic SM3 digest for a single audit record item."""
        canonical_json = json.dumps(record, sort_keys=True, separators=(",", ":"))
        return sm3_hash(canonical_json)

    @classmethod
    def compute_root_sm3_digest(cls, records: list[dict[str, str]]) -> str:
        """Calculate chain-hashed SM3 root digest across all records."""
        if not records:
            return sm3_hash("EMPTY_AUDIT_BUNDLE")

        current_digest = ""
        for rec in records:
            rec_hash = cls.calculate_record_sm3(rec)
            combined = f"{current_digest}:{rec_hash}"
            current_digest = sm3_hash(combined)

        return current_digest

    @classmethod
    def pack_bundle(
        cls,
        records: list[dict[str, str]],
        bundle_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AuditBundleRecord:
        """Pack and cryptographically seal audit records into an AuditBundleRecord."""
        bid = bundle_id or f"bundle-{uuid.uuid4().hex[:12]}"
        now = time.time()
        meta = metadata.copy() if metadata else {}
        root_digest = cls.compute_root_sm3_digest(records)

        return AuditBundleRecord(
            bundle_id=bid,
            timestamp=now,
            record_count=len(records),
            sm3_root_digest=root_digest,
            is_sealed=True,
            metadata=meta,
        )

    @classmethod
    def verify_bundle(
        cls,
        bundle: AuditBundleRecord,
        raw_records: list[dict[str, str]],
    ) -> bool:
        """Verify whether raw records match the sealed bundle's SM3 root digest."""
        if len(raw_records) != bundle.record_count:
            return False

        recalculated = cls.compute_root_sm3_digest(raw_records)
        return recalculated == bundle.sm3_root_digest
