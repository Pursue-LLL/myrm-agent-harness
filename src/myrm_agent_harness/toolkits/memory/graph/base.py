"""Graph Store Abstract Interface and Data Models.


[INPUT]
(none — leaf module, no internal dependencies)

[OUTPUT]
GraphStore: Abstract async graph store interface (CRUD + causal chain + health)
GraphNode: Pydantic model for graph nodes
GraphRelationship: Pydantic model for graph relationships
GraphQueryResult: Pydantic model for raw query results
PropertyValue, Properties: Type aliases for node/relationship properties

[POS]
Graph store abstraction layer. Defines a backend-agnostic graph storage interface and data
models for all graph store implementations. Defaults to SQLite recursive CTE; AGE optional.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

type PropertyValue = str | int | float | bool | list[str] | dict[str, str | int | float | bool]
type Properties = dict[str, PropertyValue]


class GraphNode(BaseModel):
    """Graph node with labels and properties."""

    id: str
    labels: list[str] = Field(default_factory=list)
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


class GraphRelationship(BaseModel):
    """Graph relationship between two nodes."""

    id: str
    start_id: str
    end_id: str
    rel_type: str
    properties: dict[str, str | int | float] = Field(default_factory=dict)


class GraphQueryResult(BaseModel):
    """Raw graph query result (for backends supporting direct queries like Cypher)."""

    records: list[dict[str, str | int | float | bool | list[str]]] = Field(default_factory=list)
    summary: dict[str, str | int | float | bool] | None = None


class GraphStats(BaseModel):
    """Aggregate statistics for the graph store."""

    node_count: int = 0
    relationship_count: int = 0
    node_label_counts: dict[str, int] = Field(default_factory=dict)
    relationship_type_counts: dict[str, int] = Field(default_factory=dict)


class GraphStore(ABC):
    """Abstract async graph store interface.

    Provides a unified API for graph storage and retrieval,
    supporting different backends (SQLite CTE, PostgreSQL AGE, etc.).

    All methods are async for non-blocking I/O.

    Example::

        store = SQLiteGraphStore(db_path="~/.app/graph.db")

        node = await store.create_node(
            labels=["Memory"],
            properties={"content": "important fact"}
        )

        rel = await store.create_relationship(
            start_id=node.id,
            end_id="other_id",
            rel_type="causes"
        )

        chain = await store.get_causal_chain(node.id, depth=5)
        await store.close()
    """

    @abstractmethod
    async def create_node(self, labels: list[str], properties: dict[str, str | int | float | bool]) -> GraphNode: ...

    @abstractmethod
    async def create_relationship(
        self, start_id: str, end_id: str, rel_type: str, properties: dict[str, str | int | float] | None = None
    ) -> GraphRelationship:
        """Idempotent: if a relationship with (start_id, end_id, rel_type) already
        exists, return the existing one without creating a duplicate."""
        ...

    @abstractmethod
    async def get_causal_chain(
        self, start_id: str, depth: int = 5, relation_types: list[str] | None = None
    ) -> list[str]:
        """Traverse the graph from *start_id* along *relation_types* edges.

        Returns node IDs in causal order, up to *depth* hops.
        """
        ...

    @abstractmethod
    async def delete_node(self, node_id: str) -> bool: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...

    # ── Optional methods with sensible defaults ──────────────────────

    async def get_or_create_node(
        self, labels: list[str], match_keys: list[str], properties: dict[str, str | int | float | bool]
    ) -> GraphNode:
        """Find existing node by (labels, match_keys) or create a new one."""
        return await self.create_node(labels, properties)

    async def get_related_nodes(self, node_id: str, rel_type: str = "MENTIONS") -> list[str]:
        """Find sibling node IDs sharing entities with *node_id*.

        Traverses: node → entity → other_nodes (via reverse relation).
        """
        return []

    async def get_related_nodes_with_depth(
        self, node_id: str, rel_type: str = "MENTIONS", max_depth: int = 2
    ) -> list[tuple[str, int]]:
        """Find sibling node IDs with their hop depth from *node_id*.

        Returns list of (node_id, depth) tuples where depth indicates
        how many hops away the node is (1=direct, 2=indirect, etc.).
        """
        return []

    async def delete_subgraph(self, node_id: str) -> int:
        """Delete a node and all its relationships.

        Returns the total number of deleted elements (node + relationships).
        Default implementation delegates to ``delete_node``.
        """
        deleted = await self.delete_node(node_id)
        return 1 if deleted else 0

    async def delete_all_by_owner(self, owner_id: str, *, owner_key: str = "user_id") -> int:
        """Delete all graph data owned by *owner_id*.

        Returns the total number of deleted elements.

        *owner_key* specifies which node property key stores the owner
        identifier (defaults to ``"user_id"`` for backward compatibility).
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement delete_all_by_owner. "
            "Override this method to support per-namespace cleanup."
        )

    async def execute_cypher(
        self, query: str, params: dict[str, str | int | float | bool | list[str]] | None = None
    ) -> GraphQueryResult:
        """Execute a raw graph query (Cypher or equivalent).

        Not all backends support this — SQLite raises ``GraphNotSupportedError``.
        """
        from myrm_agent_harness.toolkits.memory.graph.exceptions import GraphNotSupportedError

        raise GraphNotSupportedError(
            f"{type(self).__name__} does not support direct query execution. "
            "Use specialized methods like get_causal_chain() instead."
        )

    async def get_node(self, node_id: str) -> GraphNode | None:
        """Retrieve a single node by ID, or None if not found."""
        raise NotImplementedError(f"{type(self).__name__} does not implement get_node.")

    async def find_nodes(
        self, labels: list[str], filters: dict[str, str | int | float | bool], *, limit: int = 100
    ) -> list[GraphNode]:
        """Find nodes by exact-match properties."""
        raise NotImplementedError(f"{type(self).__name__} does not implement find_nodes.")

    async def update_node_properties(
        self, node_id: str, properties: dict[str, str | int | float | bool]
    ) -> GraphNode | None:
        """Merge and persist node properties."""
        raise NotImplementedError(f"{type(self).__name__} does not implement update_node_properties.")

    async def list_nodes(self, *, limit: int = 50, offset: int = 0) -> list[GraphNode]:
        """Paginated listing of all nodes."""
        raise NotImplementedError(f"{type(self).__name__} does not implement list_nodes.")

    async def list_relationships(self, *, limit: int = 50, offset: int = 0) -> list[GraphRelationship]:
        """Paginated listing of all relationships."""
        raise NotImplementedError(f"{type(self).__name__} does not implement list_relationships.")

    async def get_stats(self) -> GraphStats:
        """Return aggregate graph statistics."""
        raise NotImplementedError(f"{type(self).__name__} does not implement get_stats.")

    async def __aenter__(self) -> GraphStore:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object
    ) -> None:
        await self.close()
