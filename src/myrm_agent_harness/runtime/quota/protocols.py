"""Storage quota checking protocol.

Defines the protocol for checking storage quotas before writing files.
This allows the offload callback to integrate with quota management systems.

[INPUT]
- (none)

[OUTPUT]
- StorageQuotaChecker: Protocol for checking storage quotas before file writes.

[POS]
Storage quota checking protocol.
"""

from __future__ import annotations

from typing import Protocol


class StorageQuotaChecker(Protocol):
    """Protocol for checking storage quotas before file writes.

    Implementations should check if a write operation would exceed
    the user's storage quota and return True if allowed, False otherwise.
    """

    async def check_write_allowed(
        self,
        session_id: str,
        write_size_bytes: int,
    ) -> bool:
        """Check if a write operation is allowed within quota limits.

        Args:
            session_id: Session identifier (maps to user in Per-User Container model)
            write_size_bytes: Size of the content to be written in bytes

        Returns:
            True if write is allowed, False if it would exceed quota

        Example:
            >>> checker = MyQuotaChecker()
            >>> await checker.check_write_allowed("chat_abc123", 1024000)
            True
        """
        ...

    async def get_remaining_quota(self, session_id: str) -> int:
        """Get remaining storage quota in bytes.

        Args:
            session_id: Session identifier

        Returns:
            Remaining quota in bytes, or -1 if unlimited

        Example:
            >>> checker = MyQuotaChecker()
            >>> await checker.get_remaining_quota("chat_abc123")
            524288000  # 500MB remaining
        """
        ...
