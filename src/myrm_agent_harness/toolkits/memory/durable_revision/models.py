"""Data models and type definitions for durable revision safe concurrent writes."""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class ChangeReceiptStatus(StrEnum):
    """The seven authoritative statuses for a memory change receipt."""

    APPLIED = "APPLIED"
    RETRYABLE_CONTENTION = "RETRYABLE_CONTENTION"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"
    REVERTED = "REVERTED"
    FAILED_DURABLE = "FAILED_DURABLE"


class WritePayload(BaseModel):
    """Client write request payload with idempotency and optimistic locking support."""

    key: str
    content: str
    tags: dict[str, str] = Field(default_factory=dict)
    expected_revision: int | None = None
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ChangeReceipt(BaseModel):
    """Authoritative typed change receipt returned upon attempting a durable write."""

    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    status: ChangeReceiptStatus
    canonical_revision: int
    timestamp: float = Field(default_factory=lambda: time.time())
    pending_error: str | None = None
    checksum_crc32: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)


class SnapshotReadView(BaseModel):
    """Immutable point-in-time snapshot view of a memory page/document."""

    key: str
    revision: int
    content: str
    tags: dict[str, str] = Field(default_factory=dict)
    is_tombstone: bool = False
    created_at: float
    checksum_crc32: int = 0


class RevisionIntent(BaseModel):
    """Pre-commit Write-Ahead Intent logged to durable storage before mutation."""

    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    content: str
    tags: dict[str, str] = Field(default_factory=dict)
    expected_revision: int | None = None
    phase: str = "PENDING"  # PENDING | COMMITTED | FAILED
    checksum_crc32: int = 0
    created_at: float = Field(default_factory=lambda: time.time())
