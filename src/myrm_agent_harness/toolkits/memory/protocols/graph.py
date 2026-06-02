"""Graph store protocol — optional episodic causal chains.


Re-exports data models from ``toolkits.memory.graph.base`` and defines the
``GraphStoreProtocol`` — the duck-typed interface that any graph
backend must satisfy to work with the memory system.

[INPUT]
myrm_agent_harness.toolkits.memory.graph.base (POS: Graph storage abstraction layer)

[OUTPUT]
GraphStoreProtocol: Protocol for memory graph backends
GraphNode, GraphRelationship: Re-exports from toolkits.memory.graph

[POS]
Memory-system graph store protocol. Defines the graph operation interface required by the memory module; types are unified via toolkits.memory.graph.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.memory.graph.base import GraphNode, GraphRelationship, GraphStats

__all__ = [
    "GraphNode",
    "GraphRelationship",
    "GraphStats",
    "GraphStoreProtocol",
]


@runtime_checkable
class GraphStoreProtocol(Protocol):
    async def create_node(self, labels: list[str], properties: dict[str, str | int | float | bool]) -> GraphNode: ...

    async def get_or_create_node(
        self, labels: list[str], match_keys: list[str], properties: dict[str, str | int | float | bool]
    ) -> GraphNode:
        """Find an existing node by (labels, match_keys subset of properties) or create one."""
        ...

    async def create_relationship(
        self, start_id: str, end_id: str, rel_type: str, properties: dict[str, str | int | float] | None = None
    ) -> GraphRelationship: ...

    async def get_causal_chain(
        self, start_id: str, depth: int = 3, relation_types: list[str] | None = None
    ) -> list[str]: ...

    async def get_related_nodes(self, node_id: str, rel_type: str = "MENTIONS") -> list[str]:
        """Find sibling node IDs that share entities with the given node."""
        ...

    async def get_related_nodes_with_depth(
        self, node_id: str, rel_type: str = "MENTIONS", max_depth: int = 2
    ) -> list[tuple[str, int]]:
        """Find sibling node IDs with their hop depth from the given node.

        Returns list of (node_id, depth) tuples where depth indicates
        how many hops away the node is (1=direct, 2=indirect, etc.).
        """
        ...

    async def get_node(self, node_id: str) -> GraphNode | None: ...

    async def find_nodes(
        self, labels: list[str], filters: dict[str, str | int | float | bool], *, limit: int = 100
    ) -> list[GraphNode]: ...

    async def update_node_properties(
        self, node_id: str, properties: dict[str, str | int | float | bool]
    ) -> GraphNode | None: ...

    async def delete_node(self, node_id: str) -> bool: ...

    async def delete_subgraph(self, node_id: str) -> int:
        """Delete a node and all its relationships from the graph."""
        ...

    async def delete_all_by_owner(self, owner_id: str, *, owner_key: str = "user_id") -> int:
        """Delete all graph data (nodes + relationships) owned by *owner_id*."""
        ...

    async def list_nodes(self, *, limit: int = 50, offset: int = 0) -> list[GraphNode]: ...
    async def list_relationships(self, *, limit: int = 50, offset: int = 0) -> list[GraphRelationship]: ...
    async def get_stats(self) -> GraphStats: ...

    async def health_check(self) -> bool: ...
    async def close(self) -> None: ...
