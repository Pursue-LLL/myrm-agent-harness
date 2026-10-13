"""Wiki graph analysis - Community detection and knowledge insights.

[INPUT]
- math (POS: standard library math)
- sqlite3::Connection (POS: standard library database)
- .graph_tables::federated_graph_queries (POS: graph node/edge rows shared with the viewer)

[OUTPUT]
- label_propagation: LPA community detection algorithm
- compute_graph_insights: Knowledge gap and community analysis
- enrich_graph_with_communities: Assign LPA groups and degree-based sizes to graph nodes

[POS]
Pure-Python graph analysis module for wiki knowledge graph. Provides Label Propagation
community detection, knowledge gap identification, and unexpected connection discovery
over the same federated concept graph the viewer renders.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping, Sequence

from .graph_tables import federated_graph_queries

GraphRecord = dict[str, object]

_MAX_UNEXPECTED_CONNECTIONS = 20
_MAX_ISOLATED_GAPS = 15
_MAX_BRIDGE_GAPS = 15
_MAX_COMMUNITY_MEMBERS = 10
_MIN_BRIDGE_COMMUNITIES = 3
_MIN_CLUSTER_SIZE = 2


def label_propagation(
    nodes: Sequence[Mapping[str, object]], edges: Sequence[Mapping[str, object]], iterations: int = 10
) -> dict[str, int]:
    """Deterministic Label Propagation Algorithm for community detection (pure Python, no deps)."""
    if not nodes:
        return {}

    # Sort nodes for deterministic initial ordering
    sorted_nodes = sorted(nodes, key=lambda x: str(x.get("id", "")))
    labels: dict[str, int] = {str(node["id"]): i for i, node in enumerate(sorted_nodes)}
    neighbors: dict[str, list[str]] = {str(node["id"]): [] for node in sorted_nodes}

    for edge in edges:
        src, tgt = str(edge["source"]), str(edge["target"])
        if src in neighbors:
            neighbors[src].append(tgt)
        if tgt in neighbors:
            neighbors[tgt].append(src)

    # Sort neighbors deterministically
    for n_id in neighbors:
        neighbors[n_id].sort()

    node_ids = [str(n["id"]) for n in sorted_nodes]
    for _ in range(iterations):
        changed = False
        for node_id in node_ids:
            nbrs = neighbors.get(node_id, [])
            if not nbrs:
                continue
            label_counts: dict[int, int] = {}
            for nbr in nbrs:
                lbl = labels.get(nbr, 0)
                label_counts[lbl] = label_counts.get(lbl, 0) + 1
            max_count = max(label_counts.values())
            # Deterministic tie-breaking: pick the smallest label ID in tie
            best_labels = sorted([lbl for lbl, cnt in label_counts.items() if cnt == max_count])
            new_label = best_labels[0]
            if labels[node_id] != new_label:
                labels[node_id] = new_label
                changed = True
        if not changed:
            break

    unique_labels = sorted(set(labels.values()))
    label_map = {lbl: idx for idx, lbl in enumerate(unique_labels)}
    return {node_id: label_map[lbl] for node_id, lbl in labels.items()}


def enrich_graph_with_communities(nodes: list[GraphRecord], edges: Sequence[Mapping[str, object]]) -> None:
    """Assign LPA community group IDs and logarithmic-scaled degree sizes to nodes (in-place)."""
    if not nodes:
        return
    communities = label_propagation(nodes, edges)
    degree_count: dict[str, int] = {}
    for e in edges:
        src = str(e["source"])
        tgt = str(e["target"])
        degree_count[src] = degree_count.get(src, 0) + 1
        degree_count[tgt] = degree_count.get(tgt, 0) + 1
    for node in nodes:
        node_id = str(node["id"])
        node["group"] = communities.get(node_id, 0)
        deg = degree_count.get(node_id, 0)
        # Logarithmic dampening scale for visual balance: max(1, min(10, 1 + round(math.log2(deg + 1))))
        node["val"] = max(1, min(10, 1 + round(math.log2(deg + 1))))


def _load_insight_graph(conn: sqlite3.Connection) -> tuple[list[str], dict[tuple[str, str], float]]:
    """Concept pages and the directed edges between them, from the graph the viewer shows.

    Edges whose endpoint is not an indexed page (pseudo `system:*` targets, unresolved
    link text) are not part of the graph and are ignored.
    """
    names_sql, edges_sql = federated_graph_queries(conn)
    nodes = sorted(str(row["concept_name"]) for row in conn.execute(names_sql))
    known = set(nodes)
    edge_weights: dict[tuple[str, str], float] = {}
    for row in conn.execute(edges_sql):
        src, tgt = str(row["source"]), str(row["target"])
        if src == tgt or src not in known or tgt not in known:
            continue
        edge_weights[(src, tgt)] = max(edge_weights.get((src, tgt), 0.0), float(row["weight"] or 1.0))
    return nodes, edge_weights


def compute_graph_insights(conn: sqlite3.Connection) -> dict[str, list[GraphRecord]]:
    """Analyze graph structure for unexpected connections, knowledge gaps, and communities."""
    nodes, edge_weights = _load_insight_graph(conn)
    if not nodes:
        return {"unexpected_connections": [], "knowledge_gaps": [], "communities": []}

    # Undirected view: a mutual link is one connection, reported with its heaviest direction.
    pair_weight: dict[tuple[str, str], float] = {}
    pair_direction: dict[tuple[str, str], tuple[str, str]] = {}
    for (src, tgt), weight in sorted(edge_weights.items(), key=lambda item: (-item[1], item[0])):
        pair = (min(src, tgt), max(src, tgt))
        if pair not in pair_weight:
            pair_weight[pair] = weight
            pair_direction[pair] = (src, tgt)

    neighbors: dict[str, set[str]] = {node: set() for node in nodes}
    for first, second in pair_weight:
        neighbors[first].add(second)
        neighbors[second].add(first)

    communities = label_propagation(
        [{"id": node} for node in nodes],
        [{"source": src, "target": tgt} for src, tgt in edge_weights],
    )

    # 1. Unexpected connections: links crossing communities.
    crossing = sorted(
        (
            (src, tgt, pair_weight[pair])
            for pair, (src, tgt) in pair_direction.items()
            if communities[src] != communities[tgt]
        ),
        key=lambda link: (-link[2], link[0], link[1]),
    )

    # 2. Knowledge gaps: weakly linked pages and bridges, each capped separately so one
    #    kind cannot crowd out the other.
    isolated = sorted((node for node in nodes if len(neighbors[node]) <= 1), key=lambda n: (len(neighbors[n]), n))
    bridges = sorted(
        (
            (node, bridged)
            for node in nodes
            if (bridged := len({communities[nbr] for nbr in neighbors[node]})) >= _MIN_BRIDGE_COMMUNITIES
        ),
        key=lambda item: (-item[1], item[0]),
    )
    gaps: list[GraphRecord] = [
        {"node": node, "type": "isolated", "degree": len(neighbors[node])} for node in isolated[:_MAX_ISOLATED_GAPS]
    ]
    gaps.extend(
        {"node": node, "type": "bridge", "communities_connected": bridged}
        for node, bridged in bridges[:_MAX_BRIDGE_GAPS]
    )

    # 3. Community summaries: a cluster needs at least two pages (a lone page is already an
    #    isolated gap); cohesion is the share of possible member pairs that are linked.
    members_by_community: dict[int, list[str]] = {}
    for node in nodes:
        members_by_community.setdefault(communities[node], []).append(node)
    linked_pairs: dict[int, int] = {}
    for first, second in pair_weight:
        if communities[first] == communities[second]:
            linked_pairs[communities[first]] = linked_pairs.get(communities[first], 0) + 1

    community_info: list[GraphRecord] = []
    for comm_id, members in sorted(members_by_community.items(), key=lambda item: (-len(item[1]), item[0])):
        size = len(members)
        if size < _MIN_CLUSTER_SIZE:
            continue
        cohesion = linked_pairs.get(comm_id, 0) / (size * (size - 1) / 2)
        hubs_first = sorted(members, key=lambda n: (-len(neighbors[n]), n))
        community_info.append(
            {
                "id": comm_id,
                "size": size,
                "members": hubs_first[:_MAX_COMMUNITY_MEMBERS],
                "cohesion": round(cohesion, 3),
            }
        )

    return {
        "unexpected_connections": [
            {"source": src, "target": tgt, "weight": weight}
            for src, tgt, weight in crossing[:_MAX_UNEXPECTED_CONNECTIONS]
        ],
        "knowledge_gaps": gaps,
        "communities": community_info,
    }
