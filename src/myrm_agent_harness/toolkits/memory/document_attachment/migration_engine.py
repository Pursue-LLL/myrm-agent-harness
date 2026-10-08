"""Legacy attachment-to-document relationship migration and orphan cleansing engine."""

from time import perf_counter

from myrm_agent_harness.toolkits.memory.document_attachment.models import (
    MigrationLegacyEntry,
    MigrationReport,
)
from myrm_agent_harness.toolkits.memory.document_attachment.ownership_engine import (
    DocumentAttachmentOwnershipEngine,
)


class AttachmentBelongsToDocumentMigrationEngine:
    """Migrates legacy multi-associated attachments into strictly document-owned records.

    Unreferenced or hanging legacy attachments are dropped as orphans during migration.
    """

    def __init__(self, ownership_engine: DocumentAttachmentOwnershipEngine) -> None:
        self._engine: DocumentAttachmentOwnershipEngine = ownership_engine

    def migrate_legacy_entries(
        self,
        legacy_entries: list[MigrationLegacyEntry],
        blob_payloads: dict[str, bytes] | None = None,
    ) -> MigrationReport:
        """Flattens legacy multi-associated entries into document-scoped ownership items.

        Orphaned legacy records with no active document references are permanently dropped.
        """
        start_time: float = perf_counter()
        migrated_count: int = 0
        dropped_orphans: int = 0
        payloads: dict[str, bytes] = blob_payloads or {}

        for entry in legacy_entries:
            # If no document is associated, drop as orphan
            if not entry.associated_document_ids:
                dropped_orphans += 1
                continue

            content: bytes = payloads.get(
                entry.attachment_hash,
                f"placeholder_for_{entry.attachment_hash}".encode(),
            )

            # Flatten each document association into its own dedicated ownership record
            for doc_id in entry.associated_document_ids:
                self._engine.attach_to_document(
                    document_id=doc_id,
                    file_name=entry.file_name,
                    mime_type=entry.mime_type,
                    content_bytes=content,
                    precomputed_hash=entry.attachment_hash,
                )
                migrated_count += 1

        elapsed_ms: float = (perf_counter() - start_time) * 1000.0

        return MigrationReport(
            total_scanned=len(legacy_entries),
            migrated_records=migrated_count,
            dropped_orphans=dropped_orphans,
            elapsed_ms=round(elapsed_ms, 3),
        )
