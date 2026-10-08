"""Unified facade suite for durable concurrent writes and revision safety."""

from __future__ import annotations

import threading
from pathlib import Path

from myrm_agent_harness.toolkits.memory.durable_revision.lock_manager import (
    KeyLockManager,
    LockContentionTimeoutError,
)
from myrm_agent_harness.toolkits.memory.durable_revision.models import (
    ChangeReceipt,
    ChangeReceiptStatus,
    RevisionIntent,
    SnapshotReadView,
    WritePayload,
)
from myrm_agent_harness.toolkits.memory.durable_revision.revision_engine import (
    MVCCRevisionEngine,
    RevisionContentionError,
    RevisionNotFoundError,
)
from myrm_agent_harness.toolkits.memory.durable_revision.wal_recovery import (
    TwoPhaseIntentWAL,
    calculate_payload_crc32,
)


class DurableRevisionSuite:
    """Production-grade coordination facade for durable concurrent writes and MVCC snapshot reading."""

    def __init__(
        self,
        wal_dir: Path | str | None = None,
        base_backoff_sec: float = 0.010,
        max_backoff_sec: float = 0.150,
    ) -> None:
        self.lock_mgr = KeyLockManager(
            base_backoff_sec=base_backoff_sec,
            max_backoff_sec=max_backoff_sec,
        )
        self.engine = MVCCRevisionEngine()
        self.wal = TwoPhaseIntentWAL(wal_dir=wal_dir)

        self._receipt_lock = threading.Lock()
        self._receipts: dict[str, ChangeReceipt] = {}

    def _record_receipt(self, receipt: ChangeReceipt) -> ChangeReceipt:
        with self._receipt_lock:
            self._receipts[receipt.receipt_id] = receipt
            return receipt

    def write(
        self,
        payload: WritePayload,
        max_retries: int = 4,
        timeout_sec: float = 0.8,
    ) -> ChangeReceipt:
        """Execute a durable atomic write with fine-grained locking, WAL intent, and typed change receipt."""
        crc = calculate_payload_crc32(payload.key, payload.content, payload.tags)
        intent = RevisionIntent(
            key=payload.key,
            content=payload.content,
            tags=payload.tags,
            expected_revision=payload.expected_revision,
            phase="PENDING",
            checksum_crc32=crc,
        )
        self.wal.log_intent(intent)

        # Attempt fine-grained key lock acquisition with full jitter backoff
        try:
            with self.lock_mgr.acquire_lock(payload.key, max_retries=max_retries, timeout_sec=timeout_sec):
                # Verify and advance revision atomically in MVCC engine
                try:
                    new_rev, snap = self.engine.commit_mutation(
                        key=payload.key,
                        content=payload.content,
                        tags=payload.tags,
                        expected_revision=payload.expected_revision,
                    )
                except RevisionContentionError as rce:
                    self.wal.fail_intent(intent.intent_id, reason=str(rce))
                    receipt = ChangeReceipt(
                        key=payload.key,
                        status=ChangeReceiptStatus.VALIDATION_FAILED,
                        canonical_revision=self.engine.get_canonical_revision(payload.key),
                        pending_error=str(rce),
                        checksum_crc32=crc,
                        metadata={"request_id": payload.request_id},
                    )
                    return self._record_receipt(receipt)

                # Mutation succeeded: commit WAL intent
                self.wal.commit_intent(intent.intent_id)

                receipt = ChangeReceipt(
                    key=payload.key,
                    status=ChangeReceiptStatus.APPLIED,
                    canonical_revision=new_rev,
                    checksum_crc32=snap.checksum_crc32,
                    metadata={"request_id": payload.request_id, "intent_id": intent.intent_id},
                )
                return self._record_receipt(receipt)

        except LockContentionTimeoutError as lcte:
            self.wal.fail_intent(intent.intent_id, reason=str(lcte))
            receipt = ChangeReceipt(
                key=payload.key,
                status=ChangeReceiptStatus.RETRYABLE_CONTENTION,
                canonical_revision=self.engine.get_canonical_revision(payload.key),
                pending_error=str(lcte),
                checksum_crc32=crc,
                metadata={"request_id": payload.request_id},
            )
            return self._record_receipt(receipt)

    def read_snapshot(
        self,
        key: str,
        target_revision: int | None = None,
    ) -> SnapshotReadView | None:
        """Lockless point-in-time snapshot read returning content, tags, and tombstone state."""
        return self.engine.snapshot_read(key=key, target_revision=target_revision)

    def rollback(
        self,
        key: str,
        target_revision: int,
        timeout_sec: float = 0.8,
    ) -> ChangeReceipt:
        """Safely revert a key to a prior revision by committing a forward monotonic reversion revision."""
        try:
            with self.lock_mgr.acquire_lock(key, timeout_sec=timeout_sec):
                new_rev, snap = self.engine.rollback_to(key, target_revision)
                receipt = ChangeReceipt(
                    key=key,
                    status=ChangeReceiptStatus.REVERTED,
                    canonical_revision=new_rev,
                    checksum_crc32=snap.checksum_crc32,
                    metadata={"target_revision": str(target_revision)},
                )
                return self._record_receipt(receipt)
        except (LockContentionTimeoutError, RevisionNotFoundError) as e:
            receipt = ChangeReceipt(
                key=key,
                status=ChangeReceiptStatus.VALIDATION_FAILED,
                canonical_revision=self.engine.get_canonical_revision(key),
                pending_error=str(e),
            )
            return self._record_receipt(receipt)

    def retract(self, key: str, timeout_sec: float = 0.8) -> ChangeReceipt:
        """Publish a tombstone revision to retract key state while preserving audit trail."""
        try:
            with self.lock_mgr.acquire_lock(key, timeout_sec=timeout_sec):
                new_rev, snap = self.engine.mark_tombstone(key)
                receipt = ChangeReceipt(
                    key=key,
                    status=ChangeReceiptStatus.SUPERSEDED,
                    canonical_revision=new_rev,
                    checksum_crc32=snap.checksum_crc32,
                    metadata={"action": "tombstone"},
                )
                return self._record_receipt(receipt)
        except LockContentionTimeoutError as lcte:
            receipt = ChangeReceipt(
                key=key,
                status=ChangeReceiptStatus.RETRYABLE_CONTENTION,
                canonical_revision=self.engine.get_canonical_revision(key),
                pending_error=str(lcte),
            )
            return self._record_receipt(receipt)

    def quarantine(self, key: str, reason: str) -> ChangeReceipt:
        """Quarantine key edits due to anomalies or validation failures."""
        receipt = ChangeReceipt(
            key=key,
            status=ChangeReceiptStatus.QUARANTINED,
            canonical_revision=self.engine.get_canonical_revision(key),
            pending_error=reason,
        )
        return self._record_receipt(receipt)

    def get_receipt(self, receipt_id: str) -> ChangeReceipt | None:
        """Query an issued change receipt by its UUID."""
        with self._receipt_lock:
            return self._receipts.get(receipt_id)

    def recover(self) -> int:
        """Perform crash recovery: replay healed pending WAL intents and quarantine corruptions."""
        report = self.wal.scan_and_recover()
        healed_count = 0
        for intent in report.healed_intents:
            payload = WritePayload(
                key=intent.key,
                content=intent.content,
                tags=intent.tags,
                expected_revision=intent.expected_revision,
            )
            rc = self.write(payload)
            if rc.status == ChangeReceiptStatus.APPLIED:
                healed_count += 1

        for corrupted_id in report.corrupted_intent_ids:
            receipt = ChangeReceipt(
                key="unknown",
                status=ChangeReceiptStatus.FAILED_DURABLE,
                canonical_revision=0,
                pending_error=f"Corrupted WAL record {corrupted_id}",
            )
            self._record_receipt(receipt)

        return healed_count

    def get_stats(self) -> dict[str, int | float]:
        """Aggregate operational telemetry stats across locks, revisions, and receipts."""
        with self._receipt_lock:
            status_counts: dict[str, int] = {}
            for r in self._receipts.values():
                status_counts[r.status.value] = status_counts.get(r.status.value, 0) + 1

        return {
            "total_receipts": len(self._receipts),
            "applied_receipts": status_counts.get(ChangeReceiptStatus.APPLIED.value, 0),
            "contention_receipts": status_counts.get(ChangeReceiptStatus.RETRYABLE_CONTENTION.value, 0),
            "validation_failed_receipts": status_counts.get(ChangeReceiptStatus.VALIDATION_FAILED.value, 0),
            "quarantined_receipts": status_counts.get(ChangeReceiptStatus.QUARANTINED.value, 0),
            "superseded_receipts": status_counts.get(ChangeReceiptStatus.SUPERSEDED.value, 0),
            "reverted_receipts": status_counts.get(ChangeReceiptStatus.REVERTED.value, 0),
            "failed_durable_receipts": status_counts.get(ChangeReceiptStatus.FAILED_DURABLE.value, 0),
            "active_locks": self.lock_mgr.get_active_lock_count(),
            "total_snapshots": self.engine.count_total_revisions(),
        }
