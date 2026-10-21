"""Graph Store — async graph storage with SQLite CTE backend.

Features:
- GraphStore ABC with CRUD + causal chain traversal + subgraph cleanup
- Built-in SQLiteGraphStore (zero external dependencies, WAL mode)
- Pydantic data models for nodes and relationships

Example::

    from myrm_agent_harness.toolkits.memory.graph import SQLiteGraphStore

    async with SQLiteGraphStore("~/.app/graph.db") as store:
        node = await store.create_node(["Memory"], {"content": "fact"})
        chain = await store.get_causal_chain(node.id, depth=5)
"""

from myrm_agent_harness.toolkits.memory.graph.age_store import AGEStore
from myrm_agent_harness.toolkits.memory.graph.base import (
    GraphNode,
    GraphQueryResult,
    GraphRelationship,
    GraphStore,
    Properties,
    PropertyValue,
)
from myrm_agent_harness.toolkits.memory.graph.exceptions import (
    GraphConnectionError,
    GraphNodeNotFoundError,
    GraphNotSupportedError,
    GraphQueryError,
    GraphRelationshipError,
    GraphStoreError,
)
from myrm_agent_harness.toolkits.memory.graph.sqlite_store import SQLiteGraphStore

__all__ = [
    "AGEStore",
    "GraphConnectionError",
    "GraphNode",
    "GraphNodeNotFoundError",
    "GraphNotSupportedError",
    "GraphQueryError",
    "GraphQueryResult",
    "GraphRelationship",
    "GraphRelationshipError",
    "GraphStore",
    "GraphStoreError",
    "Properties",
    "PropertyValue",
    "SQLiteGraphStore",
]
