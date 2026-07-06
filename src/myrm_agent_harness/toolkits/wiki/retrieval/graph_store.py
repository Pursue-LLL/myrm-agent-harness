"""Wiki knowledge graph storage and BFS traversal.

[INPUT]
sqlite3 (POS: standard library database)
..core.structure::WikiStructure (POS: database path resolution)
.graph_analysis::enrich_graph_with_communities, compute_graph_insights (POS: graph analysis)

[OUTPUT]
WikiGraphStore: Graph topology storage, BFS traversal, and insight computation

[POS]
Encapsulates knowledge graph operations: BFS neighbor traversal, federated
graph queries across public wiki databases, and structural insight computation.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from .graph_analysis import compute_graph_insights, enrich_graph_with_communities

if TYPE_CHECKING:
    from ..core.structure import WikiStructure

ConnFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]

logger = logging.getLogger(__name__)


class WikiGraphStore:
    """Knowledge graph storage and BFS traversal over federated wiki databases."""

    def __init__(self, get_conn_fn: ConnFactory, structure: "WikiStructure") -> None:
        self._get_conn = get_conn_fn
        self._structure = structure

    def get_knowledge_graph(
        self, center_node: str | None = None, depth: int = 1, limit: int = 1000
    ) -> dict[str, list]:
        """Fetch the full topology graph in O(1) DB read time, with progressive BFS support."""
        nodes: list[dict] = []
        edges: list[dict] = []
        node_ids: set[str] = set()

        with self._get_conn() as conn:
            fts_tables = ["wiki_fts"]
            edges_tables = ["wiki_edges"]
            for idx, p_dir in enumerate(self._structure.public_dirs):
                if (p_dir / ".wiki_index.db").exists():
                    fts_tables.append(f"pub_{idx}.wiki_fts")
                    edges_tables.append(f"pub_{idx}.wiki_edges")

            fts_union = " UNION ALL ".join(f"SELECT concept_name FROM {t}" for t in fts_tables)
            edges_union = " UNION ALL ".join(
                f"SELECT source, target, weight FROM {t}" for t in edges_tables
            )

            if not center_node:
                cursor = conn.execute(
                    f"SELECT concept_name FROM ({fts_union}) LIMIT ?", (limit,)
                )
                for row in cursor.fetchall():
                    node_id = row["concept_name"]
                    nodes.append({"id": node_id, "name": node_id.replace("-", " "), "group": 1})
                    node_ids.add(node_id)

                if node_ids:
                    cursor = conn.execute(
                        f"SELECT source, target, weight FROM ({edges_union})"
                    )
                    for row in cursor.fetchall():
                        src = row["source"]
                        tgt = row["target"]
                        if src in node_ids and tgt in node_ids:
                            edges.append({
                                "source": src,
                                "target": tgt,
                                "weight": row["weight"] or 1.0,
                            })
            else:
                nodes, edges = self._bfs_from_center(
                    conn, center_node, depth, limit, fts_union, edges_union
                )

        enrich_graph_with_communities(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    def _bfs_from_center(
        self,
        conn: sqlite3.Connection,
        center_node: str,
        depth: int,
        limit: int,
        fts_union: str,
        edges_union: str,
    ) -> tuple[list[dict], list[dict]]:
        """BFS starting from center_node across federated databases."""
        nodes: list[dict] = []
        current_level = {center_node}
        visited_nodes = {center_node}
        all_edges: list[dict] = []

        cursor = conn.execute(
            f"SELECT concept_name FROM ({fts_union}) WHERE concept_name = ?",
            (center_node,),
        )
        if cursor.fetchone():
            nodes.append({
                "id": center_node,
                "name": center_node.replace("-", " "),
                "group": 1,
            })

        for _ in range(depth):
            if not current_level:
                break
            next_level: set[str] = set()

            placeholders = ",".join(["?"] * len(current_level))
            params = tuple(current_level)

            cursor = conn.execute(
                f"SELECT source, target, weight FROM ({edges_union}) WHERE source IN ({placeholders})",
                params,
            )
            for row in cursor.fetchall():
                src, tgt = row["source"], row["target"]
                all_edges.append({
                    "source": src,
                    "target": tgt,
                    "weight": row["weight"] or 1.0,
                })
                if tgt not in visited_nodes:
                    next_level.add(tgt)

            cursor = conn.execute(
                f"SELECT source, target, weight FROM ({edges_union}) WHERE target IN ({placeholders})",
                params,
            )
            for row in cursor.fetchall():
                src, tgt = row["source"], row["target"]
                all_edges.append({
                    "source": src,
                    "target": tgt,
                    "weight": row["weight"] or 1.0,
                })
                if src not in visited_nodes:
                    next_level.add(src)

            if next_level:
                np_placeholders = ",".join(["?"] * len(next_level))
                np_params = tuple(next_level)
                cursor = conn.execute(
                    f"SELECT concept_name FROM ({fts_union}) WHERE concept_name IN ({np_placeholders})",
                    np_params,
                )
                for row in cursor.fetchall():
                    nid = row["concept_name"]
                    if nid not in visited_nodes:
                        nodes.append({
                            "id": nid,
                            "name": nid.replace("-", " "),
                            "group": 1,
                        })
                        visited_nodes.add(nid)

            current_level = next_level
            if len(visited_nodes) >= limit:
                break

        unique_edges: dict[tuple[str, str], dict] = {}
        for e in all_edges:
            if e["source"] in visited_nodes and e["target"] in visited_nodes:
                unique_edges[(e["source"], e["target"])] = e

        return nodes, list(unique_edges.values())

    def graph_insights(self) -> dict[str, list[dict]]:
        """Analyze graph structure for unexpected connections, knowledge gaps, and communities."""
        with self._get_conn() as conn:
            return compute_graph_insights(conn)
