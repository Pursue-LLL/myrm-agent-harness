"""Unit tests for Durable Revision Suite (concurrent writes and snapshot safety)."""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from myrm_agent_harness.toolkits.memory.durable_revision import (
    ChangeReceiptStatus,
    DurableRevisionSuite,
    RevisionIntent,
    WritePayload,
    calculate_payload_crc32,
    compute_jitter_backoff,
)


def test_jitter_backoff_distribution() -> None:
    """Verify exponential jitter backoff stays bounded and positive."""
    for r in range(5):
        val = compute_jitter_backoff(retry=r, base_sec=0.010, max_sec=0.100)
        assert 0.005 <= val <= 0.100


def test_basic_write_and_snapshot_read() -> None:
    """Verify single-threaded monotonic write and point-in-time snapshot reading."""
    suite = DurableRevisionSuite()
    payload1 = WritePayload(
        key="doc/arch_notes",
        content="Initial draft of micro-kernel design",
        tags={"author": "architect", "stage": "draft"},
    )

    rc1 = suite.write(payload1)
    assert rc1.status == ChangeReceiptStatus.APPLIED
    assert rc1.canonical_revision == 1
    assert rc1.key == "doc/arch_notes"
    assert rc1.checksum_crc32 != 0

    # Query snapshot
    snap1 = suite.read_snapshot("doc/arch_notes")
    assert snap1 is not None
    assert snap1.revision == 1
    assert snap1.content == "Initial draft of micro-kernel design"
    assert snap1.tags == {"author": "architect", "stage": "draft"}
    assert not snap1.is_tombstone

    # Second write advances canonical revision
    payload2 = WritePayload(
        key="doc/arch_notes",
        content="Second iteration of micro-kernel design",
        tags={"author": "architect", "stage": "review"},
    )
    rc2 = suite.write(payload2)
    assert rc2.status == ChangeReceiptStatus.APPLIED
    assert rc2.canonical_revision == 2

    snap2 = suite.read_snapshot("doc/arch_notes")
    assert snap2 is not None
    assert snap2.revision == 2
    assert snap2.content == "Second iteration of micro-kernel design"


def test_point_in_time_historical_snapshot_read() -> None:
    """Verify MVCC capability to locklessly read historical immutable snapshots."""
    suite = DurableRevisionSuite()
    key = "fact/user_preference"

    # Commit 3 distinct versions
    suite.write(WritePayload(key=key, content="Prefers Python"))
    suite.write(WritePayload(key=key, content="Prefers Rust"))
    suite.write(WritePayload(key=key, content="Prefers Go"))

    # Read specific historical slices
    s1 = suite.read_snapshot(key, target_revision=1)
    s2 = suite.read_snapshot(key, target_revision=2)
    s3 = suite.read_snapshot(key, target_revision=3)

    assert s1 is not None and s1.content == "Prefers Python"
    assert s2 is not None and s2.content == "Prefers Rust"
    assert s3 is not None and s3.content == "Prefers Go"

    # Non-existent revision
    s99 = suite.read_snapshot(key, target_revision=99)
    assert s99 is None


def test_concurrent_writes_fine_grained_locking_and_jitter() -> None:
    """Stress test fine-grained key locking and retry backoff across parallel threads."""
    suite = DurableRevisionSuite(base_backoff_sec=0.005, max_backoff_sec=0.040)
    key = "shared/concurrent_document"
    thread_count = 8

    def worker(worker_id: int) -> ChangeReceiptStatus:
        p = WritePayload(
            key=key,
            content=f"Update from worker {worker_id}",
            tags={"worker": str(worker_id)},
        )
        rc = suite.write(p, max_retries=6, timeout_sec=2.0)
        return rc.status

    with ThreadPoolExecutor(max_workers=thread_count) as pool:
        results = list(pool.map(worker, range(thread_count)))

    # All parallel writes should complete either as APPLIED or gracefully as RETRYABLE_CONTENTION
    applied_count = sum(1 for s in results if s == ChangeReceiptStatus.APPLIED)
    contention_count = sum(1 for s in results if s == ChangeReceiptStatus.RETRYABLE_CONTENTION)
    assert applied_count + contention_count == thread_count
    assert applied_count >= 1

    latest = suite.read_snapshot(key)
    assert latest is not None
    assert latest.revision == applied_count


def test_optimistic_revision_validation_contention() -> None:
    """Verify expected_revision optimistic concurrency check produces VALIDATION_FAILED receipt."""
    suite = DurableRevisionSuite()
    key = "ledger/balance"

    # Initial write creates revision 1
    rc1 = suite.write(WritePayload(key=key, content="Balance: 100"))
    assert rc1.canonical_revision == 1

    # Conflict write expects revision 99
    rc_fail = suite.write(
        WritePayload(key=key, content="Balance: 150", expected_revision=99)
    )
    assert rc_fail.status == ChangeReceiptStatus.VALIDATION_FAILED
    assert rc_fail.canonical_revision == 1
    assert rc_fail.pending_error is not None
    assert "Revision validation failed" in rc_fail.pending_error

    # Successful write with matching expected_revision 1
    rc_ok = suite.write(
        WritePayload(key=key, content="Balance: 200", expected_revision=1)
    )
    assert rc_ok.status == ChangeReceiptStatus.APPLIED
    assert rc_ok.canonical_revision == 2


def test_safe_rollback_and_retract_tombstone() -> None:
    """Verify forward monotonic rollback and tombstone retraction."""
    suite = DurableRevisionSuite()
    key = "policy/access_rules"

    suite.write(WritePayload(key=key, content="V1: Allow all", tags={"rule": "v1"}))
    suite.write(WritePayload(key=key, content="V2: Restrict all", tags={"rule": "v2"}))

    # Revert to revision 1 (emits revision 3 with V1's content)
    rc_revert = suite.rollback(key, target_revision=1)
    assert rc_revert.status == ChangeReceiptStatus.REVERTED
    assert rc_revert.canonical_revision == 3

    snap3 = suite.read_snapshot(key)
    assert snap3 is not None
    assert snap3.content == "V1: Allow all"
    assert snap3.tags == {"rule": "v1"}

    # Retract / Tombstone
    rc_retract = suite.retract(key)
    assert rc_retract.status == ChangeReceiptStatus.SUPERSEDED
    assert rc_retract.canonical_revision == 4

    snap4 = suite.read_snapshot(key)
    assert snap4 is not None
    assert snap4.is_tombstone
    assert snap4.content == ""


def test_two_phase_wal_crash_recovery_and_isolation() -> None:
    """Verify crash recovery heals uncommitted valid intents and quarantines corruptions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        wal_path = Path(tmp_dir) / "wal"
        suite1 = DurableRevisionSuite(wal_dir=wal_path)

        # Log an uncommitted but valid intent directly into WAL
        crc = calculate_payload_crc32("doc/recovered", "Rescued content", {"tag": "wal"})
        intent_valid = RevisionIntent(
            key="doc/recovered",
            content="Rescued content",
            tags={"tag": "wal"},
            checksum_crc32=crc,
            phase="PENDING",
        )
        suite1.wal.log_intent(intent_valid)

        # Log a corrupted intent
        intent_bad = RevisionIntent(
            key="doc/corrupted",
            content="Partial content bytes...",
            tags={},
            checksum_crc32=999999999,  # Bad CRC
            phase="PENDING",
        )
        suite1.wal.log_intent(intent_bad)

        # Simulate crash restart by creating fresh suite pointing to same WAL directory
        suite2 = DurableRevisionSuite(wal_dir=wal_path)
        healed_count = suite2.recover()
        assert healed_count == 1

        recovered_snap = suite2.read_snapshot("doc/recovered")
        assert recovered_snap is not None
        assert recovered_snap.content == "Rescued content"

        stats = suite2.get_stats()
        assert stats["total_receipts"] >= 2
        assert stats["failed_durable_receipts"] >= 1
