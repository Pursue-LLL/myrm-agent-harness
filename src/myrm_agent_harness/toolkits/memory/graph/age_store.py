"""Apache AGE Graph Store — enterprise-grade graph backend for SaaS deployments.

Uses PostgreSQL + Apache AGE extension for full Cypher support and ACID transactions.

[INPUT]
- (none)

[OUTPUT]
- AGEStore: Apache AGE graph store (SaaS mode).

[POS]
Apache AGE Graph Store — enterprise-grade graph backend for SaaS deployments.
"""

import asyncio
import logging

from myrm_agent_harness.toolkits.memory.graph.base import GraphNode, GraphQueryResult, GraphRelationship, GraphStore
from myrm_agent_harness.toolkits.memory.graph.exceptions import GraphConnectionError, GraphQueryError

logger = logging.getLogger(__name__)


class AGEStore(GraphStore):
    """Apache AGE graph store (SaaS mode).

    Example::

        store = AGEStore(dsn="postgresql://...", graph_name="episodic_memory")
        node = await store.create_node(["Memory"], {"content": "..."})
        await store.close()
    """

    def __init__(self, dsn: str, graph_name: str = "episodic_memory") -> None:
        self._dsn = dsn
        self._graph_name = graph_name

        try:
            from age import Age

            self._age = Age()
            self._age.connect(dsn=dsn, graph=graph_name)
            logger.info("AGEStore initialized: graph='%s'", graph_name)
        except ImportError as e:
            msg = "apache-age-python is required for AGEStore. Install with: uv add apache-age-python --group sandbox"
            logger.error(msg)
            raise ImportError(msg) from e
        except Exception as e:
            msg = f"Failed to connect to Apache AGE: {e}"
            logger.error(msg)
            raise GraphConnectionError(msg) from e

    async def execute_cypher(
        self, query: str, params: dict[str, str | int | float | bool | list[str]] | None = None
    ) -> GraphQueryResult:
        def _execute() -> GraphQueryResult:
            try:
                cursor = self._age.execCypher(query, params or {})
                records = [dict(row) for row in cursor]
                return GraphQueryResult(records=records)
            except Exception as e:
                raise GraphQueryError(f"Cypher query failed: {e}") from e

        return await asyncio.to_thread(_execute)

    async def create_node(self, labels: list[str], properties: dict[str, str | int | float | bool]) -> GraphNode:
        try:
            labels_str = ":".join(labels) if labels else "Node"
            query = f"CREATE (n:{labels_str} $props) RETURN n, id(n) as node_id"
            result = await self.execute_cypher(query, {"props": properties})

            if result.records:
                record = result.records[0]
                return GraphNode(id=str(record["node_id"]), labels=labels, properties=properties)
            raise GraphQueryError("Failed to create node: no records returned")
        except GraphQueryError:
            raise
        except Exception as e:
            raise GraphQueryError(f"Failed to create node: {e}") from e

    async def get_or_create_node(
        self, labels: list[str], match_keys: list[str], properties: dict[str, str | int | float | bool]
    ) -> GraphNode:
        labels_str = ":".join(labels) if labels else "Node"
        where_parts = [f"n.{k} = $match_{k}" for k in match_keys]
        cypher_params: dict[str, str | int | float | bool | list[str]] = {
            f"match_{k}": properties[k] for k in match_keys
        }

        query = f"MATCH (n:{labels_str}) WHERE {' AND '.join(where_parts)} RETURN n, id(n) as node_id LIMIT 1"
        result = await self.execute_cypher(query, cypher_params)
        if result.records:
            record = result.records[0]
            return GraphNode(
                id=str(record["node_id"]), labels=labels, properties=dict(record["n"]) if record["n"] else properties
            )
        return await self.create_node(labels, properties)

    async def create_relationship(
        self, start_id: str, end_id: str, rel_type: str, properties: dict[str, str | int | float] | None = None
    ) -> GraphRelationship:
        """Idempotent: uses MERGE to avoid duplicate relationships."""
        query = f"""
        MATCH (a), (b)
        WHERE id(a) = $start_id AND id(b) = $end_id
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r += $props
        RETURN id(r) as rel_id
        """
        result = await self.execute_cypher(
            query,
            {
                "start_id": int(start_id),
                "end_id": int(end_id),
                "props": properties or {},
            },
        )
        if result.records:
            return GraphRelationship(
                id=str(result.records[0]["rel_id"]),
                start_id=start_id,
                end_id=end_id,
                rel_type=rel_type,
                properties=properties or {},
            )
        raise GraphQueryError("Failed to create relationship: no records returned")

    async def get_causal_chain(
        self, start_id: str, depth: int = 5, relation_types: list[str] | None = None
    ) -> list[str]:
        if relation_types is None:
            relation_types = ["CAUSES"]
        type_pattern = "|".join(t.upper() for t in relation_types)
        query = f"""
        MATCH path = (start)-[:{type_pattern}*1..{depth}]->(related)
        WHERE id(start) = $start_id
        RETURN id(related) as node_id, length(path) as depth
        ORDER BY depth
        """
        result = await self.execute_cypher(query, {"start_id": int(start_id)})
        return [str(r["node_id"]) for r in result.records]

    async def get_related_nodes(self, node_id: str, rel_type: str = "MENTIONS") -> list[str]:
        query = f"""
        MATCH (m)-[:{rel_type}]->(e)<-[:{rel_type}]-(sibling)
        WHERE id(m) = $node_id AND id(sibling) <> $node_id
        RETURN DISTINCT id(sibling) as sibling_id
        """
        try:
            result = await self.execute_cypher(query, {"node_id": int(node_id)})
            return [str(r["sibling_id"]) for r in result.records]
        except Exception as e:
            logger.warning("get_related_nodes failed: %s", e)
            return []

    async def get_related_nodes_with_depth(
        self, node_id: str, rel_type: str = "MENTIONS", max_depth: int = 2
    ) -> list[tuple[str, int]]:
        query = f"""
        MATCH path = (m)-[:{rel_type}*1..{max_depth}]-(sibling)
        WHERE id(m) = $node_id AND id(sibling) <> $node_id
        RETURN DISTINCT id(sibling) as sibling_id, length(path) as depth
        ORDER BY depth
        """
        try:
            result = await self.execute_cypher(query, {"node_id": int(node_id)})
            return [(str(r["sibling_id"]), int(r["depth"])) for r in result.records]
        except Exception as e:
            logger.warning("get_related_nodes_with_depth failed: %s", e)
            return []

    async def delete_subgraph(self, node_id: str) -> int:
        query = "MATCH (n) WHERE id(n) = $id DETACH DELETE n RETURN count(*) as cnt"
        try:
            result = await self.execute_cypher(query, {"id": int(node_id)})
            return int(result.records[0]["cnt"]) if result.records else 0
        except Exception as e:
            logger.warning("delete_subgraph failed for %s: %s", node_id, e)
            return 0

    async def delete_all_by_owner(self, owner_id: str, *, owner_key: str = "user_id") -> int:
        query = f"""
        MATCH (n) WHERE n.{owner_key} = $owner_id
        DETACH DELETE n RETURN count(*) as cnt
        """
        try:
            result = await self.execute_cypher(query, {"owner_id": owner_id})
            return int(result.records[0]["cnt"]) if result.records else 0
        except Exception as e:
            logger.warning("delete_all_by_owner failed for %s: %s", owner_id, e)
            return 0

    async def get_node(self, node_id: str) -> GraphNode | None:
        query = """
        MATCH (n) WHERE id(n) = $id
        RETURN n, labels(n) as labels, id(n) as node_id
        """
        result = await self.execute_cypher(query, {"id": int(node_id)})
        if result.records:
            record = result.records[0]
            node_data = record["n"]
            return GraphNode(
                id=str(record["node_id"]), labels=record["labels"], properties=dict(node_data) if node_data else {}
            )
        return None

    async def delete_node(self, node_id: str) -> bool:
        query = "MATCH (n) WHERE id(n) = $id DETACH DELETE n"
        await self.execute_cypher(query, {"id": int(node_id)})
        return True

    async def health_check(self) -> bool:
        try:
            await self.execute_cypher("RETURN 1")
            return True
        except Exception as e:
            logger.error("AGE health check failed: %s", e)
            return False

    async def close(self) -> None:
        if self._age and hasattr(self._age, "connection"):
            self._age.connection.close()
        logger.info("AGEStore closed")
