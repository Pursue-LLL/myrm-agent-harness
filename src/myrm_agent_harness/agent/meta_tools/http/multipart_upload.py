"""Multipart Upload - S3-Compatible Concurrent Upload for Large Files

[INPUT]

[OUTPUT]
- S3-compatible multipart upload protocol

[POS]
Multipart upload interface (framework layer). Defines an S3-compatible multipart upload protocol for business-layer adapters.

"""

from __future__ import annotations

from typing import Protocol


class MultipartUploadAdapter(Protocol):
    """S3-compatible multipart upload adapter protocol (Framework layer interface)

    Business layer should implement this protocol to provide S3-compatible multipart upload.
    Framework layer only defines the interface, does not couple with specific cloud storage implementation.

    Supported cloud storage services (S3-compatible):
    - AWS S3
    - MinIO
    - Ceph (RGW)
    - Alibaba Cloud OSS (S3-compatible mode)
    - Azure Blob Storage (S3-compatible mode)

    Example implementation:
    - S3MultipartAdapter: AWS S3 / MinIO / Ceph multipart upload (using boto3/aioboto3)
    """

    async def init_multipart_upload(self, bucket: str, key: str) -> str:
        """Initialize multipart upload

        Args:
            bucket: S3 bucket name
            key: Object key (file path in bucket)

        Returns:
            upload_id: Unique multipart upload identifier

        Example:
            upload_id = await adapter.init_multipart_upload(bucket="my-bucket", key="data/file.bin")
        """
        ...

    async def upload_part(self, bucket: str, key: str, upload_id: str, part_number: int, data: bytes) -> str:
        """Upload single part

        Args:
            bucket: S3 bucket name
            key: Object key
            upload_id: Multipart upload identifier
            part_number: Part number (1-based)
            data: Part data bytes

        Returns:
            etag: ETag of uploaded part (for completion)

        Example:
            etag = await adapter.upload_part(
                bucket="my-bucket",
                key="data/file.bin",
                upload_id="upload-123",
                part_number=1,
                data=b"part 1 data..."
            )
        """
        ...

    async def complete_multipart_upload(self, bucket: str, key: str, upload_id: str, parts: list[dict]) -> None:
        """Complete multipart upload

        Args:
            bucket: S3 bucket name
            key: Object key
            upload_id: Multipart upload identifier
            parts: List of uploaded parts (format: [{"PartNumber": int, "ETag": str}])

        Example:
            await adapter.complete_multipart_upload(
                bucket="my-bucket",
                key="data/file.bin",
                upload_id="upload-123",
                parts=[{"PartNumber": 1, "ETag": "etag-1"}, {"PartNumber": 2, "ETag": "etag-2"}]
            )
        """
        ...

    async def abort_multipart_upload(self, bucket: str, key: str, upload_id: str) -> None:
        """Abort multipart upload (cleanup orphaned parts)

        Args:
            bucket: S3 bucket name
            key: Object key
            upload_id: Multipart upload identifier

        Example:
            await adapter.abort_multipart_upload(bucket="my-bucket", key="data/file.bin", upload_id="upload-123")
        """
        ...
