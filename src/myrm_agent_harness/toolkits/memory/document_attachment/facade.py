"""Unified facade for document attachment lifecycle, ownership, and reclaim sweeps."""

from pathlib import Path

from myrm_agent_harness.toolkits.memory.document_attachment.migration_engine import (
    AttachmentBelongsToDocumentMigrationEngine,
)
from myrm_agent_harness.toolkits.memory.document_attachment.models import (
    AttachmentOwnershipItem,
    AttachmentStats,
    MigrationLegacyEntry,
    MigrationReport,
    ReclaimAuditReport,
    StorageBlobMetadata,
)
from myrm_agent_harness.toolkits.memory.document_attachment.ownership_engine import (
    DocumentAttachmentOwnershipEngine,
)
from myrm_agent_harness.toolkits.memory.document_attachment.reclaim_sweep import (
    DeterministicReclaimSweeper,
)


class DocumentAttachmentSuite:
    """Unified entry point for document-owned attachment management.

    Provides deterministic garbage collection and orphan-cleansing migration.
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._ownership_engine: DocumentAttachmentOwnershipEngine = DocumentAttachmentOwnershipEngine(
            storage_dir=storage_dir
        )
        self._sweeper: DeterministicReclaimSweeper = DeterministicReclaimSweeper(
            ownership_engine=self._ownership_engine
        )
        self._migration_engine: AttachmentBelongsToDocumentMigrationEngine = AttachmentBelongsToDocumentMigrationEngine(
            ownership_engine=self._ownership_engine
        )

    @property
    def ownership_engine(self) -> DocumentAttachmentOwnershipEngine:
        """Returns the underlying ownership engine."""
        return self._ownership_engine

    @property
    def sweeper(self) -> DeterministicReclaimSweeper:
        """Returns the deterministic GC sweeper."""
        return self._sweeper

    @property
    def migration_engine(self) -> AttachmentBelongsToDocumentMigrationEngine:
        """Returns the legacy relationship migration engine."""
        return self._migration_engine

    def attach(
        self,
        document_id: str,
        file_name: str,
        mime_type: str,
        content: bytes,
    ) -> AttachmentOwnershipItem:
        """Attaches content to a document, updating ownership and shared blob ref count."""
        return self._ownership_engine.attach_to_document(
            document_id=document_id,
            file_name=file_name,
            mime_type=mime_type,
            content_bytes=content,
        )

    def get_document_attachments(
        self,
        document_id: str,
    ) -> list[AttachmentOwnershipItem]:
        """Retrieves all attachment items owned by a document."""
        return self._ownership_engine.get_document_attachments(document_id=document_id)

    def get_attachment(
        self,
        document_id: str,
        attachment_id: str,
    ) -> AttachmentOwnershipItem | None:
        """Retrieves an attachment metadata record if owned by the specified document."""
        return self._ownership_engine.get_attachment(
            document_id=document_id,
            attachment_id=attachment_id,
        )

    def detach(self, document_id: str, attachment_id: str) -> bool:
        """Detaches an attachment from a document and decrements the blob ref count."""
        return self._ownership_engine.detach_from_document(
            document_id=document_id,
            attachment_id=attachment_id,
        )

    def remove_document(self, document_id: str) -> int:
        """Removes all attachments belonging to a document and decrements blob ref counts."""
        return self._ownership_engine.remove_document(document_id=document_id)

    def sweep(self) -> ReclaimAuditReport:
        """Executes a deterministic sweep to unlink and purge unreferenced storage blobs."""
        return self._sweeper.sweep()

    def migrate(
        self,
        legacy_entries: list[MigrationLegacyEntry],
        blob_payloads: dict[str, bytes] | None = None,
    ) -> MigrationReport:
        """Flattens legacy multi-associated entries and drops orphaned unlinked blobs."""
        return self._migration_engine.migrate_legacy_entries(
            legacy_entries=legacy_entries,
            blob_payloads=blob_payloads,
        )

    def get_stats(self) -> AttachmentStats:
        """Computes current attachment, document, and physical blob statistics."""
        all_blobs: list[StorageBlobMetadata] = self._ownership_engine.get_all_storage_blobs()
        total_bytes: int = sum(b.byte_size for b in all_blobs)
        unclaimed_keys: int = sum(1 for b in all_blobs if b.ref_count <= 0)

        return AttachmentStats(
            total_documents=self._ownership_engine.get_document_count(),
            total_attachment_rows=self._ownership_engine.get_total_attachment_count(),
            total_storage_keys=len(all_blobs),
            total_physical_bytes=total_bytes,
            orphaned_unclaimed_keys=unclaimed_keys,
        )
