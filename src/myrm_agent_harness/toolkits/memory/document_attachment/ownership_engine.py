"""Document attachment ownership and reference count tracking engine."""

import threading
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.toolkits.memory.document_attachment.models import (
    AttachmentOwnershipItem,
    StorageBlobMetadata,
)


class DocumentAttachmentOwnershipEngine:
    """Manages document-level attachment metadata and shared blob reference counting."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir: Path | None = storage_dir
        if self._storage_dir is not None:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
        # document_id -> (attachment_id -> AttachmentOwnershipItem)
        self._doc_attachments: dict[str, dict[str, AttachmentOwnershipItem]] = {}
        # storage_key -> StorageBlobMetadata
        self._storage_blobs: dict[str, StorageBlobMetadata] = {}
        # attachment_hash -> storage_key
        self._hash_to_key: dict[str, str] = {}
        self._lock: threading.Lock = threading.Lock()

    def attach_to_document(
        self,
        document_id: str,
        file_name: str,
        mime_type: str,
        content_bytes: bytes,
        precomputed_hash: str | None = None,
    ) -> AttachmentOwnershipItem:
        """Attaches a blob to a document, updating ownership and blob reference count.

        If the content hash already exists, shares the existing physical storage_key
        and increments the reference count.
        """
        attachment_hash: str = precomputed_hash if precomputed_hash is not None else sha256(content_bytes).hexdigest()
        byte_size: int = len(content_bytes)
        attachment_id: str = f"att_{uuid4().hex[:12]}"

        with self._lock:
            if attachment_hash in self._hash_to_key:
                storage_key: str = self._hash_to_key[attachment_hash]
                blob_meta: StorageBlobMetadata = self._storage_blobs[storage_key]
                blob_meta.increment()
            else:
                storage_key = f"blob_{attachment_hash[:16]}"
                physical_path: str | None = None
                if self._storage_dir is not None:
                    target_file: Path = self._storage_dir / f"{storage_key}.blob"
                    target_file.write_bytes(content_bytes)
                    physical_path = str(target_file)

                blob_meta = StorageBlobMetadata(
                    storage_key=storage_key,
                    attachment_hash=attachment_hash,
                    byte_size=byte_size,
                    ref_count=1,
                    physical_path=physical_path,
                )
                self._storage_blobs[storage_key] = blob_meta
                self._hash_to_key[attachment_hash] = storage_key

            item = AttachmentOwnershipItem(
                attachment_id=attachment_id,
                document_id=document_id,
                attachment_hash=attachment_hash,
                storage_key=storage_key,
                file_name=file_name,
                mime_type=mime_type,
                byte_size=byte_size,
            )

            if document_id not in self._doc_attachments:
                self._doc_attachments[document_id] = {}
            self._doc_attachments[document_id][attachment_id] = item

            return item

    def get_document_attachments(self, document_id: str) -> list[AttachmentOwnershipItem]:
        """Lists all attachment ownership records scoped to the specified document."""
        with self._lock:
            doc_map: dict[str, AttachmentOwnershipItem] = self._doc_attachments.get(document_id, {})
            return list(doc_map.values())

    def get_attachment(
        self,
        document_id: str,
        attachment_id: str,
    ) -> AttachmentOwnershipItem | None:
        """Retrieves a single attachment metadata item owned by the document."""
        with self._lock:
            return self._doc_attachments.get(document_id, {}).get(attachment_id)

    def detach_from_document(self, document_id: str, attachment_id: str) -> bool:
        """Removes the attachment record from the document and decrements ref count."""
        with self._lock:
            doc_map = self._doc_attachments.get(document_id)
            if not doc_map or attachment_id not in doc_map:
                return False

            item: AttachmentOwnershipItem = doc_map.pop(attachment_id)
            if not doc_map:
                self._doc_attachments.pop(document_id, None)

            # Decrement reference on the underlying blob
            blob_meta = self._storage_blobs.get(item.storage_key)
            if blob_meta is not None:
                blob_meta.decrement()

            return True

    def remove_document(self, document_id: str) -> int:
        """Removes all attachments belonging to a document and decrements ref counts.

        Returns the number of attachments detached.
        """
        with self._lock:
            doc_map = self._doc_attachments.pop(document_id, None)
            if not doc_map:
                return 0

            count: int = len(doc_map)
            for item in doc_map.values():
                blob_meta = self._storage_blobs.get(item.storage_key)
                if blob_meta is not None:
                    blob_meta.decrement()

            return count

    def get_storage_blob(self, storage_key: str) -> StorageBlobMetadata | None:
        """Retrieves the physical storage metadata for a storage key."""
        with self._lock:
            return self._storage_blobs.get(storage_key)

    def get_all_storage_blobs(self) -> list[StorageBlobMetadata]:
        """Returns snapshot list of all tracked storage blob metadata."""
        with self._lock:
            return list(self._storage_blobs.values())

    def internal_remove_storage_blob(self, storage_key: str) -> StorageBlobMetadata | None:
        """Internal helper invoked by sweeper to remove a finalized blob entry."""
        with self._lock:
            blob: StorageBlobMetadata | None = self._storage_blobs.pop(storage_key, None)
            if blob and blob.attachment_hash in self._hash_to_key:
                self._hash_to_key.pop(blob.attachment_hash, None)
            return blob

    def get_document_count(self) -> int:
        """Returns total number of documents with active attachments."""
        with self._lock:
            return len(self._doc_attachments)

    def get_total_attachment_count(self) -> int:
        """Returns total count of document-attachment association rows."""
        with self._lock:
            return sum(len(sub) for sub in self._doc_attachments.values())
