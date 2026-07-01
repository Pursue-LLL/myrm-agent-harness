"""Graph analysis — impact radius, hub/bridge detection, community detection.

Provides structural code analysis operations on top of the CodeGraphStore,
including BFS-based impact radius, NetworkX-based centrality analysis, and
optional igraph Leiden community detection.

[INPUT]
- CodeGraphStore (POS: opened graph store with populated data)

[OUTPUT]
- CodeGraphAnalyzer: analysis operations over the code knowledge graph
- HotspotResult: hub/bridge detection result
- CommunityResult: community detection result

[POS]
Structural analysis layer that transforms raw graph data into actionable
insights for Agent decision-making (impact assessment, refactoring targets,
code organization understanding).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from myrm_agent_harness.toolkits.code_graph.store import (
    CodeGraphStore,
    ImpactResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HotspotEntry:
    """A single hotspot node with centrality scores."""

    qualified_name: str
    file_path: str
    kind: str
    in_degree: int = 0
    out_degree: int = 0
    betweenness: float = 0.0
    is_hub: bool = False
    is_bridge: bool = False


@dataclass(slots=True)
class HotspotResult:
    """Result of hub/bridge detection analysis."""

    hotspots: list[HotspotEntry] = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0


@dataclass(frozen=True, slots=True)
class CommunityEntry:
    """A detected code community (module cluster)."""

    community_id: int
    members: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    size: int = 0


@dataclass(slots=True)
class CommunityResult:
    """Result of community detection."""

    communities: list[CommunityEntry] = field(default_factory=list)
    modularity: float = 0.0
    method: str = "file_grouping"


class CodeGraphAnalyzer:
    """Structural analysis operations on the code knowledge graph."""

    def __init__(self, store: CodeGraphStore) -> None:
        self._store = store

    def impact_radius(
        self,
        qualified_name: str,
        *,
        max_depth: int = 5,
        max_nodes: int = 200,
    ) -> ImpactResult:
        """Delegate to store's BFS-based impact radius."""
        return self._store.impact_radius(
            qualified_name, max_depth=max_depth, max_nodes=max_nodes,
        )

    def detect_hotspots(self, *, top_k: int = 20) -> HotspotResult:
        """Detect hub and bridge nodes using degree + betweenness centrality.

        Hubs: high in-degree (many dependants).
        Bridges: high betweenness (sits on critical paths between modules).
        """
        stats = self._store.get_stats()
        if stats["nodes"] == 0:
            return HotspotResult(total_nodes=0, total_edges=0)

        db = self._store.connection

        in_degrees: dict[str, int] = {}
        out_degrees: dict[str, int] = {}
        for row in db.execute(
            "SELECT target_qualified, COUNT(*) AS cnt FROM edges GROUP BY target_qualified"
        ).fetchall():
            in_degrees[row["target_qualified"]] = row["cnt"]

        for row in db.execute(
            "SELECT source_qualified, COUNT(*) AS cnt FROM edges GROUP BY source_qualified"
        ).fetchall():
            out_degrees[row["source_qualified"]] = row["cnt"]

        all_names = set(in_degrees.keys()) | set(out_degrees.keys())

        betweenness: dict[str, float] = {}
        try:
            betweenness = self._compute_betweenness(db)
        except Exception as exc:
            logger.debug("Betweenness computation skipped: %s", exc)

        candidates: list[HotspotEntry] = []
        for qn in all_names:
            node_row = db.execute(
                "SELECT kind, file_path FROM nodes WHERE qualified_name = ?", (qn,),
            ).fetchone()
            if not node_row:
                continue

            in_d = in_degrees.get(qn, 0)
            out_d = out_degrees.get(qn, 0)
            btw = betweenness.get(qn, 0.0)

            in_threshold = max(3, stats["nodes"] * 0.05)
            is_hub = in_d >= in_threshold
            is_bridge = btw > 0.1

            candidates.append(HotspotEntry(
                qualified_name=qn,
                file_path=node_row["file_path"],
                kind=node_row["kind"],
                in_degree=in_d,
                out_degree=out_d,
                betweenness=round(btw, 4),
                is_hub=is_hub,
                is_bridge=is_bridge,
            ))

        candidates.sort(key=lambda h: h.in_degree * 2 + h.out_degree + h.betweenness * 100, reverse=True)

        return HotspotResult(
            hotspots=candidates[:top_k],
            total_nodes=stats["nodes"],
            total_edges=stats["edges"],
        )

    def detect_communities(self, *, max_communities: int = 50) -> CommunityResult:
        """Detect code communities using Leiden algorithm or file-grouping fallback."""
        try:
            return self._leiden_communities(max_communities)
        except ImportError:
            logger.debug("igraph not available, falling back to file grouping")
            return self._file_grouping_communities(max_communities)

    def _leiden_communities(self, max_communities: int) -> CommunityResult:
        """Community detection using igraph's Leiden algorithm."""
        import igraph as ig

        db = self._store.connection
        nodes_map: dict[str, int] = {}
        node_files: dict[str, str] = {}

        for row in db.execute("SELECT qualified_name, file_path FROM nodes").fetchall():
            idx = len(nodes_map)
            nodes_map[row["qualified_name"]] = idx
            node_files[row["qualified_name"]] = row["file_path"]

        if not nodes_map:
            return CommunityResult(method="leiden")

        edges: list[tuple[int, int]] = []
        for row in db.execute("SELECT source_qualified, target_qualified FROM edges").fetchall():
            src_idx = nodes_map.get(row["source_qualified"])
            tgt_idx = nodes_map.get(row["target_qualified"])
            if src_idx is not None and tgt_idx is not None and src_idx != tgt_idx:
                edges.append((src_idx, tgt_idx))

        if not edges:
            return CommunityResult(method="leiden")

        g = ig.Graph(n=len(nodes_map), edges=edges, directed=True)
        partition = g.community_leiden(objective_function="modularity")

        idx_to_name = {v: k for k, v in nodes_map.items()}

        communities: dict[int, list[str]] = {}
        for idx, comm_id in enumerate(partition.membership):
            qn = idx_to_name.get(idx, "")
            if qn:
                communities.setdefault(comm_id, []).append(qn)

        result_communities: list[CommunityEntry] = []
        for comm_id, members in sorted(communities.items(), key=lambda x: -len(x[1])):
            if len(result_communities) >= max_communities:
                break
            file_paths = sorted({node_files.get(m, "") for m in members} - {""})
            result_communities.append(CommunityEntry(
                community_id=comm_id,
                members=members,
                file_paths=file_paths,
                size=len(members),
            ))

        return CommunityResult(
            communities=result_communities,
            modularity=round(partition.modularity, 4),
            method="leiden",
        )

    def _file_grouping_communities(self, max_communities: int) -> CommunityResult:
        """Fallback: group nodes by file path as pseudo-communities."""
        db = self._store.connection
        file_groups: dict[str, list[str]] = {}

        for row in db.execute("SELECT qualified_name, file_path FROM nodes").fetchall():
            file_groups.setdefault(row["file_path"], []).append(row["qualified_name"])

        communities: list[CommunityEntry] = []
        for idx, (fpath, members) in enumerate(
            sorted(file_groups.items(), key=lambda x: -len(x[1]))
        ):
            if idx >= max_communities:
                break
            communities.append(CommunityEntry(
                community_id=idx,
                members=members,
                file_paths=[fpath],
                size=len(members),
            ))

        return CommunityResult(
            communities=communities,
            modularity=0.0,
            method="file_grouping",
        )

    @staticmethod
    def _compute_betweenness(db: sqlite3.Connection) -> dict[str, float]:
        """Compute betweenness centrality using NetworkX."""
        import networkx as nx

        G = nx.DiGraph()
        for row in db.execute(
            "SELECT source_qualified, target_qualified, confidence FROM edges"
        ).fetchall():
            G.add_edge(row["source_qualified"], row["target_qualified"], weight=row["confidence"])

        if G.number_of_nodes() == 0:
            return {}

        k = min(100, G.number_of_nodes())
        return nx.betweenness_centrality(G, k=k, weight="weight")
