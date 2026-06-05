"""Wiki graph analysis - Community detection and knowledge insights.

[INPUT]
random (POS: standard library random)
sqlite3::Connection (POS: standard library database)

[OUTPUT]
label_propagation: LPA community detection algorithm
compute_graph_insights: Knowledge gap and community analysis
enrich_graph_with_communities: Assign LPA groups and degree-based sizes to graph nodes

[POS]
Pure-Python graph analysis module for wiki knowledge graph. Provides Label Propagation
community detection, knowledge gap identification, and unexpected connection discovery.
"""

from __future__ import annotations

import random as _rnd
import sqlite3


def label_propagation(nodes: list[dict], edges: list[dict], iterations: int = 10) -> dict[str, int]:
    """Label Propagation Algorithm for community detection (pure Python, no deps)."""
    labels: dict[str, int] = {node["id"]: i for i, node in enumerate(nodes)}
    neighbors: dict[str, list[str]] = {node["id"]: [] for node in nodes}

    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        if src in neighbors:
            neighbors[src].append(tgt)
        if tgt in neighbors:
            neighbors[tgt].append(src)

    node_ids = [n["id"] for n in nodes]
    for _ in range(iterations):
        _rnd.shuffle(node_ids)
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
            best_labels = [lbl for lbl, cnt in label_counts.items() if cnt == max_count]
            new_label = _rnd.choice(best_labels)
            if labels[node_id] != new_label:
                labels[node_id] = new_label
                changed = True
        if not changed:
            break

    unique_labels = sorted(set(labels.values()))
    label_map = {lbl: idx for idx, lbl in enumerate(unique_labels)}
    return {node_id: label_map[lbl] for node_id, lbl in labels.items()}


def enrich_graph_with_communities(nodes: list[dict], edges: list[dict]) -> None:
    """Assign LPA community group IDs and degree-based sizes to nodes (in-place)."""
    if not nodes:
        return
    communities = label_propagation(nodes, edges)
    degree_count: dict[str, int] = {}
    for e in edges:
        degree_count[e["source"]] = degree_count.get(e["source"], 0) + 1
        degree_count[e["target"]] = degree_count.get(e["target"], 0) + 1
    for node in nodes:
        node["group"] = communities.get(node["id"], 0)
        node["val"] = max(1, degree_count.get(node["id"], 0))


def compute_graph_insights(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Analyze graph structure for unexpected connections, knowledge gaps, and communities."""
    cursor = conn.execute("SELECT concept_name FROM wiki_fts")
    all_nodes = [row["concept_name"] for row in cursor.fetchall()]

    cursor = conn.execute("SELECT source, target, weight FROM wiki_edges")
    all_edges = [(row["source"], row["target"], row["weight"] or 1.0) for row in cursor.fetchall()]

    if not all_nodes:
        return {"unexpected_connections": [], "knowledge_gaps": [], "communities": []}

    # Build adjacency
    neighbors: dict[str, set[str]] = {n: set() for n in all_nodes}
    for src, tgt, _ in all_edges:
        if src in neighbors:
            neighbors[src].add(tgt)
        if tgt in neighbors:
            neighbors[tgt].add(src)

    # Detect communities via LPA
    nodes_data = [{"id": n} for n in all_nodes]
    edges_data = [{"source": s, "target": t, "weight": w} for s, t, w in all_edges]
    communities = label_propagation(nodes_data, edges_data)

    # Group nodes by community
    community_groups: dict[int, list[str]] = {}
    for node_id, comm_id in communities.items():
        community_groups.setdefault(comm_id, []).append(node_id)

    # 1. Unexpected connections: edges crossing communities
    unexpected: list[dict] = []
    for src, tgt, weight in all_edges:
        if communities.get(src, -1) != communities.get(tgt, -1):
            unexpected.append({"source": src, "target": tgt, "weight": weight})
    unexpected.sort(key=lambda x: x["weight"], reverse=True)

    # 2. Knowledge gaps: isolated nodes (0-1 connections) and bridge nodes
    gaps: list[dict] = []
    for node_id in all_nodes:
        degree = len(neighbors.get(node_id, set()))
        if degree <= 1:
            gaps.append({"node": node_id, "type": "isolated", "degree": degree})

    for node_id in all_nodes:
        nbr_communities = {communities.get(n, -1) for n in neighbors.get(node_id, set())}
        if len(nbr_communities) >= 3:
            gaps.append({"node": node_id, "type": "bridge", "communities_connected": len(nbr_communities)})

    # 3. Community summaries
    community_info: list[dict] = []
    for comm_id, members in sorted(community_groups.items()):
        internal_edges = sum(
            1 for s, t, _ in all_edges if communities.get(s) == comm_id and communities.get(t) == comm_id
        )
        max_possible = len(members) * (len(members) - 1) / 2
        cohesion = internal_edges / max_possible if max_possible > 0 else 0
        community_info.append(
            {
                "id": comm_id,
                "size": len(members),
                "members": members[:10],
                "cohesion": round(cohesion, 3),
            }
        )

    return {
        "unexpected_connections": unexpected[:20],
        "knowledge_gaps": gaps[:30],
        "communities": community_info,
    }
