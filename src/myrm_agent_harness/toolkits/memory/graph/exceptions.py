"""Graph store exceptions.

[INPUT]
- (none)

[OUTPUT]
- GraphStoreError: Base exception for all graph store operations.
- GraphConnectionError: Raised when a database connection cannot be established o...
- GraphQueryError: Raised when a query execution fails.
- GraphNodeNotFoundError: Raised when a referenced node does not exist.
- GraphRelationshipError: Raised when a relationship operation fails.

[POS]
Graph store exceptions.
"""


class GraphStoreError(Exception):
    """Base exception for all graph store operations."""


class GraphConnectionError(GraphStoreError):
    """Raised when a database connection cannot be established or maintained."""


class GraphQueryError(GraphStoreError):
    """Raised when a query execution fails."""


class GraphNodeNotFoundError(GraphStoreError):
    """Raised when a referenced node does not exist."""


class GraphRelationshipError(GraphStoreError):
    """Raised when a relationship operation fails."""


class GraphNotSupportedError(GraphStoreError):
    """Raised when an unsupported operation is attempted (e.g. Cypher on SQLite)."""
