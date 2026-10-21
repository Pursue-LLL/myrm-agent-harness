"""Storage quota related errors.

[INPUT]
- (none)

[OUTPUT]
- StorageQuotaError: Base class for storage quota errors.
- QuotaExceededError: Raised when a write operation would exceed storage quota.

[POS]
Storage quota related errors.
"""

from __future__ import annotations


class StorageQuotaError(Exception):
    """Base class for storage quota errors."""

    pass


class QuotaExceededError(StorageQuotaError):
    """Raised when a write operation would exceed storage quota.

    Attributes:
        session_id: Session identifier
        requested_bytes: Requested write size in bytes
        available_bytes: Available quota in bytes
    """

    def __init__(
        self,
        message: str,
        session_id: str,
        requested_bytes: int,
        available_bytes: int,
    ) -> None:
        """Initialize QuotaExceededError.

        Args:
            message: Error message
            session_id: Session identifier
            requested_bytes: Requested write size in bytes
            available_bytes: Available quota in bytes
        """
        super().__init__(message)
        self.session_id = session_id
        self.requested_bytes = requested_bytes
        self.available_bytes = available_bytes
