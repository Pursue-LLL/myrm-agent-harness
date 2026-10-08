"""Comprehensive test suite for DocumentAttachmentSuite and ownership architecture."""

from pathlib import Path

from myrm_agent_harness.toolkits.memory import (
    AttachmentBelongsToDocumentMigrationEngine,
    AttachmentOwnershipItem,
    AttachmentStats,
    DeterministicReclaimSweeper,
    DocumentAttachmentOwnershipEngine,
    DocumentAttachmentSuite,
    MigrationLegacyEntry,
    MigrationReport,
    ReclaimAuditReport,
    StorageBlobMetadata,
)


def test_top_level_import_export() -> None:
    """Verifies that all components are exported from the top-level memory namespace."""
    assert DocumentAttachmentSuite is not None
    assert DocumentAttachmentOwnershipEngine is not None
    assert DeterministicReclaimSweeper is not None
    assert AttachmentBelongsToDocumentMigrationEngine is not None
    assert AttachmentOwnershipItem is not None
    assert StorageBlobMetadata is not None
    assert ReclaimAuditReport is not None
    assert MigrationLegacyEntry is not None
    assert MigrationReport is not None
    assert AttachmentStats is not None


def test_basic_attachment_ownership() -> None:
    """Verifies single document attachment creation and retrieval."""
    suite = DocumentAttachmentSuite()
    content: bytes = b"test content for document alpha"

    item = suite.attach(
        document_id="doc_001",
        file_name="alpha.txt",
        mime_type="text/plain",
        content=content,
    )

    assert item.document_id == "doc_001"
    assert item.file_name == "alpha.txt"
    assert item.byte_size == len(content)
    assert item.storage_key.startswith("blob_")

    # Retrieve
    retrieved = suite.get_attachment("doc_001", item.attachment_id)
    assert retrieved is not None
    assert retrieved.attachment_id == item.attachment_id

    # List attachments
    items = suite.get_document_attachments("doc_001")
    assert len(items) == 1
    assert items[0].attachment_id == item.attachment_id


def test_multi_document_shared_blob_ref_count() -> None:
    """Verifies that duplicate blobs across documents share storage_key and increment ref count."""
    suite = DocumentAttachmentSuite()
    shared_content: bytes = b"shared diagram payload 12345"

    item_a = suite.attach(
        document_id="doc_a",
        file_name="diagram.png",
        mime_type="image/png",
        content=shared_content,
    )
    item_b = suite.attach(
        document_id="doc_b",
        file_name="diagram_copy.png",
        mime_type="image/png",
        content=shared_content,
    )

    # Different attachment IDs, same storage key
    assert item_a.attachment_id != item_b.attachment_id
    assert item_a.storage_key == item_b.storage_key

    blob_meta = suite.ownership_engine.get_storage_blob(item_a.storage_key)
    assert blob_meta is not None
    assert blob_meta.ref_count == 2

    # Detach from doc_a
    detached = suite.detach("doc_a", item_a.attachment_id)
    assert detached is True
    assert blob_meta.ref_count == 1

    # GC Sweep should retain the blob
    report = suite.sweep()
    assert report.reclaimed_blobs == 0
    assert report.retained_blobs == 1

    # Detach from doc_b
    detached_b = suite.detach("doc_b", item_b.attachment_id)
    assert detached_b is True
    assert blob_meta.ref_count == 0

    # Second GC Sweep should reclaim the blob
    report_2 = suite.sweep()
    assert report_2.reclaimed_blobs == 1
    assert report_2.freed_bytes == len(shared_content)
    assert item_a.storage_key in report_2.reclaimed_storage_keys


def test_cascade_document_removal_and_deterministic_reclaim() -> None:
    """Verifies removing a document cascades to all its attachments and decrements ref counts."""
    suite = DocumentAttachmentSuite()
    content_1: bytes = b"chart 1"
    content_2: bytes = b"chart 2"

    suite.attach("doc_parent", "c1.png", "image/png", content_1)
    suite.attach("doc_parent", "c2.png", "image/png", content_2)

    stats_before = suite.get_stats()
    assert stats_before.total_documents == 1
    assert stats_before.total_attachment_rows == 2
    assert stats_before.total_storage_keys == 2

    # Remove document
    count = suite.remove_document("doc_parent")
    assert count == 2

    # Verify attachments empty
    assert len(suite.get_document_attachments("doc_parent")) == 0

    # Sweep reclaims both
    report = suite.sweep()
    assert report.reclaimed_blobs == 2
    assert report.freed_bytes == len(content_1) + len(content_2)

    stats_after = suite.get_stats()
    assert stats_after.total_storage_keys == 0


def test_physical_disk_unlink_with_storage_dir(tmp_path: Path) -> None:
    """Verifies that physical files in storage_dir are created and deleted during sweep."""
    suite = DocumentAttachmentSuite(storage_dir=tmp_path)
    content: bytes = b"hello binary blob file on physical disk"

    item = suite.attach("doc_disk", "file.bin", "application/octet-stream", content)
    disk_file = tmp_path / f"{item.storage_key}.blob"
    assert disk_file.exists()
    assert disk_file.read_bytes() == content

    # Detach and sweep
    suite.detach("doc_disk", item.attachment_id)
    report = suite.sweep()

    assert report.reclaimed_blobs == 1
    assert not disk_file.exists()


def test_legacy_migration_and_orphan_cleansing() -> None:
    """Verifies that unreferenced legacy entries are dropped as orphans and valid entries flattened."""
    suite = DocumentAttachmentSuite()

    legacy_entries = [
        MigrationLegacyEntry(
            legacy_id="leg_001",
            attachment_hash="hash_valid_1",
            file_name="report.pdf",
            mime_type="application/pdf",
            byte_size=1024,
            associated_document_ids=("doc_x", "doc_y"),
        ),
        MigrationLegacyEntry(
            legacy_id="leg_002",
            attachment_hash="hash_orphan_1",
            file_name="ghost.jpg",
            mime_type="image/jpeg",
            byte_size=2048,
            associated_document_ids=(),  # Orphan with no parent document
        ),
    ]

    report = suite.migrate(legacy_entries)
    assert report.total_scanned == 2
    assert report.migrated_records == 2  # doc_x and doc_y
    assert report.dropped_orphans == 1

    # Verify doc_x and doc_y own the item
    docs_x = suite.get_document_attachments("doc_x")
    docs_y = suite.get_document_attachments("doc_y")
    assert len(docs_x) == 1
    assert len(docs_y) == 1
    assert docs_x[0].attachment_hash == "hash_valid_1"
    assert docs_y[0].attachment_hash == "hash_valid_1"
    assert docs_x[0].storage_key == docs_y[0].storage_key
