"""Relational store exceptions.

[INPUT]
- (none)

[OUTPUT]
- RelationalStoreError: Base exception for relational store operations.
- RelationalConnectionError: Failed to connect to the relational store.
- RelationalQueryError: A relational query failed.
- RelationalNotFoundError: Requested record not found.

[POS]
Relational store exceptions.
"""


class RelationalStoreError(Exception):
    """Base exception for relational store operations."""


class RelationalConnectionError(RelationalStoreError):
    """Failed to connect to the relational store."""


class RelationalQueryError(RelationalStoreError):
    """A relational query failed."""


class RelationalNotFoundError(RelationalStoreError):
    """Requested record not found."""


class CorruptedMemoryIndexError(RelationalStoreError):
    """Raised when memory relational store or search index is physically corrupted / malformed."""

    def __init__(
        self,
        message: str,
        *,
        db_path: str = "",
        index_type: str = "sqlite_relational",
        repair_suggestion: str = "",
    ) -> None:
        super().__init__(message)
        self.db_path = db_path
        self.index_type = index_type
        self.repair_suggestion = repair_suggestion

