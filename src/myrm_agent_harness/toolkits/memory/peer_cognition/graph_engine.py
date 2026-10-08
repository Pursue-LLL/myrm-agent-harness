# [POS]: myrm_agent_harness.toolkits.memory.peer_cognition.graph_engine
# [INPUT]: models.py
# [OUTPUT]: PeerCognitionGraphStore

"""In-memory and indexed graph store for peer-centric social cognition entities.

P0 delivery for Item 110 in topic_01 memory roadmap.
Maintains relational topology connecting peers (users, agents, reviewers, projects)
with directed semantic edges (asserts, approves, collaborates_with, governs).

[INPUT]
- toolkits.memory.peer_cognition.models::PeerIdentity, PeerRelationEdge, PeerRelationKind, PeerType (POS:
  Domain models for peer-centric social cognition entity graph and agent persona cards.)

[OUTPUT]
- PeerCognitionGraphStore: Graph repository maintaining peer identity nodes and relational edges.

[POS]
In-memory and indexed graph store for peer-centric social cognition entities.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.peer_cognition.models import (
    PeerIdentity,
    PeerRelationEdge,
    PeerRelationKind,
    PeerType,
)

logger = logging.getLogger(__name__)


class PeerCognitionGraphStore:
    """Graph repository maintaining peer identity nodes and relational edges."""

    def __init__(self) -> None:
        self._peers: dict[str, PeerIdentity] = {}
        self._edges: dict[str, PeerRelationEdge] = {}
        # Forward index: source_peer_id -> list of edge_ids
        self._source_index: dict[str, list[str]] = {}
        # Reverse index: target_entity_id -> list of edge_ids
        self._target_index: dict[str, list[str]] = {}

    def register_peer(self, peer: PeerIdentity) -> PeerIdentity:
        """Register or update a peer identity node."""
        self._peers[peer.peer_id] = peer
        if peer.peer_id not in self._source_index:
            self._source_index[peer.peer_id] = []
        if peer.peer_id not in self._target_index:
            self._target_index[peer.peer_id] = []
        logger.debug("Registered peer identity: %s (%s)", peer.peer_id, peer.peer_type)
        return peer

    def get_peer(self, peer_id: str) -> PeerIdentity | None:
        """Look up a peer identity by identifier."""
        return self._peers.get(peer_id)

    def list_peers(self, peer_type: PeerType | None = None) -> list[PeerIdentity]:
        """List registered peers, optionally filtered by peer type."""
        if peer_type is None:
            return list(self._peers.values())
        return [p for p in self._peers.values() if p.peer_type == peer_type]

    def touch_peer(self, peer_id: str) -> None:
        """Update last seen timestamp for a peer upon active interaction."""
        peer = self._peers.get(peer_id)
        if peer:
            peer.last_seen_at = datetime.now(UTC).isoformat()

    def add_edge(self, edge: PeerRelationEdge) -> PeerRelationEdge:
        """Insert a directed relationship edge into the social cognition graph."""
        self._edges[edge.edge_id] = edge

        # Update source index
        if edge.source_peer_id not in self._source_index:
            self._source_index[edge.source_peer_id] = []
        if edge.edge_id not in self._source_index[edge.source_peer_id]:
            self._source_index[edge.source_peer_id].append(edge.edge_id)

        # Update target index
        if edge.target_entity_id not in self._target_index:
            self._target_index[edge.target_entity_id] = []
        if edge.edge_id not in self._target_index[edge.target_entity_id]:
            self._target_index[edge.target_entity_id].append(edge.edge_id)

        logger.debug(
            "Added relation edge %s: %s -[%s]-> %s",
            edge.edge_id,
            edge.source_peer_id,
            edge.relation_kind,
            edge.target_entity_id,
        )
        return edge

    def remove_edge(self, edge_id: str) -> bool:
        """Remove a relation edge by identifier."""
        edge = self._edges.pop(edge_id, None)
        if not edge:
            return False

        if edge.source_peer_id in self._source_index:
            self._source_index[edge.source_peer_id] = [
                eid for eid in self._source_index[edge.source_peer_id] if eid != edge_id
            ]
        if edge.target_entity_id in self._target_index:
            self._target_index[edge.target_entity_id] = [
                eid for eid in self._target_index[edge.target_entity_id] if eid != edge_id
            ]
        return True

    def list_edges(
        self,
        source_peer_id: str | None = None,
        relation_kind: PeerRelationKind | None = None,
    ) -> list[PeerRelationEdge]:
        """List edges with optional source filter and relation kind filter."""
        candidates: list[PeerRelationEdge]
        if source_peer_id is not None:
            edge_ids = self._source_index.get(source_peer_id, [])
            candidates = [self._edges[eid] for eid in edge_ids if eid in self._edges]
        else:
            candidates = list(self._edges.values())

        if relation_kind is not None:
            return [e for e in candidates if e.relation_kind == relation_kind]
        return candidates

    def get_edges_for_peer(self, peer_id: str) -> list[PeerRelationEdge]:
        """Retrieve all outgoing and incoming edges involving a given peer."""
        result: list[PeerRelationEdge] = []
        seen: set[str] = set()

        for eid in self._source_index.get(peer_id, []):
            if eid in self._edges and eid not in seen:
                result.append(self._edges[eid])
                seen.add(eid)

        for eid in self._target_index.get(peer_id, []):
            if eid in self._edges and eid not in seen:
                result.append(self._edges[eid])
                seen.add(eid)

        return result

    def get_peers_connected_to_entity(
        self,
        entity_id: str,
        relation_kind: PeerRelationKind | None = None,
    ) -> list[tuple[PeerIdentity, PeerRelationEdge]]:
        """Trace which peers are linked to an entity (e.g. who asserts or approves this fact)."""
        edge_ids = self._target_index.get(entity_id, [])
        matches: list[tuple[PeerIdentity, PeerRelationEdge]] = []

        for eid in edge_ids:
            edge = self._edges.get(eid)
            if not edge:
                continue
            if relation_kind is not None and edge.relation_kind != relation_kind:
                continue
            peer = self._peers.get(edge.source_peer_id)
            if peer:
                matches.append((peer, edge))

        return matches

    def find_collaborators(self, peer_id: str) -> list[tuple[PeerIdentity, PeerRelationEdge]]:
        """Find other peers with direct collaboration edges to this peer."""
        collaborators: list[tuple[PeerIdentity, PeerRelationEdge]] = []
        for edge in self.get_edges_for_peer(peer_id):
            if edge.relation_kind == PeerRelationKind.COLLABORATES_WITH:
                other_id = (
                    edge.target_entity_id
                    if edge.source_peer_id == peer_id
                    else edge.source_peer_id
                )
                other_peer = self._peers.get(other_id)
                if other_peer:
                    collaborators.append((other_peer, edge))
        return collaborators
