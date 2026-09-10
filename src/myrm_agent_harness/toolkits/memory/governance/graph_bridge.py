"""Entity Graph Bridge for Memory Governance.

Bridges the GraphStore with memory assembly, enforcing a strict 2-hop radius
and node-budget limit (depth <= 2, max_nodes <= 15) to prevent graph explosion.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.graph.base import GraphNode, GraphStore

logger = logging.getLogger(__name__)


class EntityGraphBridge:
    """Bridge for bounded 2-hop entity relation retrieval."""

    def __init__(self, graph_store: GraphStore | None = None) -> None:
        self._graph_store: GraphStore | None = graph_store

    def set_graph_store(self, graph_store: GraphStore) -> None:
        """Set or update the underlying GraphStore instance."""
        self._graph_store = graph_store

    async def get_bounded_subgraph_text(
        self,
        seed_entity_names: Sequence[str],
        max_depth: int = 2,
        max_nodes: int = 15,
    ) -> str:
        """Retrieve bounded relation chains for given seed entities.

        Guarantees:
        - Max traversal depth <= 2 hops
        - Max total entities retrieved <= 15
        - Formatted as concise, deterministic relation lines
        """
        if self._graph_store is None or not seed_entity_names:
            return ""

        enforced_depth = min(max_depth, 2)
        enforced_limit = min(max_nodes, 15)

        try:
            # 1. Fetch available nodes to build node lookup
            all_nodes = await self._graph_store.list_nodes(limit=100)
            node_map: dict[str, GraphNode] = {n.id: n for n in all_nodes}

            # Locate seed nodes
            seed_nodes: list[GraphNode] = []
            for name in seed_entity_names:
                clean_name = name.strip()
                if not clean_name:
                    continue
                matched = [
                    n
                    for n in all_nodes
                    if n.id == clean_name
                    or str(n.properties.get("name", "")).lower() == clean_name.lower()
                ]
                if not matched:
                    direct_node = await self._graph_store.get_node(clean_name)
                    if direct_node:
                        matched = [direct_node]
                        node_map[direct_node.id] = direct_node
                seed_nodes.extend(matched)

            if not seed_nodes:
                return ""

            # 2. Fetch relationships for traversal
            all_rels = await self._graph_store.list_relationships(limit=100)
            visited_node_ids: set[str] = {s.id for s in seed_nodes}
            relation_lines: list[str] = []

            # Multi-layer BFS up to enforced_depth
            current_layer_ids = {s.id for s in seed_nodes}
            for _ in range(enforced_depth):
                next_layer_ids: set[str] = set()
                for rel in all_rels:
                    if len(visited_node_ids) >= enforced_limit:
                        break

                    target_id: str | None = None
                    source_id: str | None = None

                    if rel.start_id in current_layer_ids:
                        source_id = rel.start_id
                        target_id = rel.end_id
                    elif rel.end_id in current_layer_ids:
                        source_id = rel.end_id
                        target_id = rel.start_id

                    if source_id is not None and target_id is not None:
                        source_node = node_map.get(source_id)
                        target_node = node_map.get(target_id)
                        s_name = (
                            str(source_node.properties.get("name", source_id))
                            if source_node
                            else source_id
                        )
                        t_name = (
                            str(target_node.properties.get("name", target_id))
                            if target_node
                            else target_id
                        )
                        relation_lines.append(f"{s_name} --[{rel.rel_type}]--> {t_name}")

                        if target_id not in visited_node_ids:
                            visited_node_ids.add(target_id)
                            next_layer_ids.add(target_id)

                current_layer_ids = next_layer_ids
                if not current_layer_ids or len(visited_node_ids) >= enforced_limit:
                    break

            if not relation_lines:
                for s in seed_nodes:
                    name_val = s.properties.get("name", s.id)
                    label = s.labels[0] if s.labels else "Entity"
                    relation_lines.append(f"{name_val} ({label})")

            unique_lines = sorted(set(relation_lines))
            return "\n".join(unique_lines)

        except Exception as e:
            logger.warning("Error fetching bounded subgraph context: %s", e)
            return ""
