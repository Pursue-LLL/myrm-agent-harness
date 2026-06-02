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
