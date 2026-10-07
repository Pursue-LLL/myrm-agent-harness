# ============================================================================
# # SessionDagGraph - Conversation Tree DAG & Branching Engine (Item 144)
# # Provides in-session Edit-From-Here branching, standalone session forks,
# # linear projection backtracking, and branch navigator metadata (< 1/N >).
# ============================================================================

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Mapping

from .session_dag_types import (
    BranchNavigatorMeta,
    SessionDagNode,
    StandaloneForkResult,
)


class SessionDagGraph:
    """Manages conversational messages structured as a Directed Acyclic Graph (DAG)."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id: str = session_id or f"sess-{uuid.uuid4().hex[:12]}"
        self.nodes: dict[str, SessionDagNode] = {}
        self.root_node_ids: list[str] = []
        self.active_leaf_id: str | None = None

    def add_message(
        self,
        role: str,
        content: str,
        parent_id: str | None = None,
        branch_id: str | None = None,
        metadata: dict[str, str | int | float | bool] | None = None,
    ) -> SessionDagNode:
        """Appends a new message node onto the DAG.

        If parent_id is omitted:
        - If the graph is empty, creates a root node.
        - If graph is not empty, defaults parent to active_leaf_id.
        """
        node_id = f"msg-{uuid.uuid4().hex[:12]}"
        actual_parent_id = parent_id if parent_id is not None else self.active_leaf_id

        # Determine branch identifier
        if branch_id is not None:
            actual_branch = branch_id
        elif actual_parent_id is not None and actual_parent_id in self.nodes:
            actual_branch = self.nodes[actual_parent_id].branch_id
        else:
            actual_branch = "main"

        new_node = SessionDagNode(
            node_id=node_id,
            parent_id=actual_parent_id,
            children_ids=[],
            branch_id=actual_branch,
            role=role,
            content=content,
            metadata=dict(metadata or {}),
            created_at=time.time(),
        )

        self.nodes[node_id] = new_node

        if actual_parent_id is None:
            self.root_node_ids.append(node_id)
        else:
            if actual_parent_id in self.nodes:
                self.nodes[actual_parent_id].children_ids.append(node_id)

        self.active_leaf_id = node_id
        return new_node

    def branch_from_node(
        self,
        target_node_id: str,
        new_content: str,
        role: str = "user",
        branch_id: str | None = None,
        metadata: dict[str, str | int | float | bool] | None = None,
    ) -> SessionDagNode:
        """Performs 'Edit from here' (in-session branch).

        Creates a sibling node originating from target_node_id's parent,
        or creates a new alternative branch child of target_node_id.
        """
        if target_node_id not in self.nodes:
            raise KeyError(f"Target node '{target_node_id}' not found in DAG.")

        target_node = self.nodes[target_node_id]
        parent_id = target_node.parent_id

        # Allocate distinct branch ID
        new_branch = branch_id or f"branch-{uuid.uuid4().hex[:8]}"
        new_node_id = f"msg-{uuid.uuid4().hex[:12]}"

        new_node = SessionDagNode(
            node_id=new_node_id,
            parent_id=parent_id,
            children_ids=[],
            branch_id=new_branch,
            role=role,
            content=new_content,
            metadata=dict(metadata or {}),
            created_at=time.time(),
        )

        self.nodes[new_node_id] = new_node

        if parent_id is not None and parent_id in self.nodes:
            self.nodes[parent_id].children_ids.append(new_node_id)
        else:
            self.root_node_ids.append(new_node_id)

        self.active_leaf_id = new_node_id
        return new_node

    def fork_standalone_session(
        self,
        fork_point_node_id: str,
        new_session_id: str | None = None,
    ) -> tuple[SessionDagGraph, StandaloneForkResult]:
        """Performs 'New session' (standalone session clone).

        Clones the linear ancestor path from root up to fork_point_node_id
        into a completely isolated, independent new SessionDagGraph.
        """
        if fork_point_node_id not in self.nodes:
            raise KeyError(f"Fork point '{fork_point_node_id}' not found in DAG.")

        linear_nodes = self.get_linear_path(fork_point_node_id)
        new_id = new_session_id or f"sess-{uuid.uuid4().hex[:12]}"
        new_graph = SessionDagGraph(session_id=new_id)

        copied_count = 0
        preview: list[str] = []
        new_active_leaf: str = ""

        # Deep clone each node on the chain
        for node in linear_nodes:
            cloned_node = copy.deepcopy(node)
            # Filter children_ids to only retain members within the new graph
            cloned_node.children_ids = [
                cid for cid in cloned_node.children_ids if any(n.node_id == cid for n in linear_nodes)
            ]
            new_graph.nodes[cloned_node.node_id] = cloned_node
            copied_count += 1
            preview.append(f"[{cloned_node.role}] {cloned_node.content[:60]}")
            new_active_leaf = cloned_node.node_id

        if linear_nodes:
            new_graph.root_node_ids = [linear_nodes[0].node_id]
            new_graph.active_leaf_id = new_active_leaf

        result = StandaloneForkResult(
            new_session_id=new_id,
            origin_session_id=self.session_id,
            forked_from_node_id=fork_point_node_id,
            copied_nodes_count=copied_count,
            active_leaf_node_id=new_active_leaf,
            linear_history_preview=preview,
        )
        return new_graph, result

    def get_linear_path(self, target_node_id: str | None = None) -> list[SessionDagNode]:
        """Backtracks from the target node (or active leaf) to Root, returning linear message path."""
        leaf_id = target_node_id if target_node_id is not None else self.active_leaf_id
        if leaf_id is None or leaf_id not in self.nodes:
            return []

        path: list[SessionDagNode] = []
        curr_id: str | None = leaf_id
        visited: set[str] = set()

        while curr_id is not None and curr_id in self.nodes:
            if curr_id in visited:
                break  # Prevent cycle loop
            visited.add(curr_id)
            node = self.nodes[curr_id]
            path.append(node)
            curr_id = node.parent_id

        path.reverse()
        return path

    def switch_active_branch(self, target_node_id: str) -> list[SessionDagNode]:
        """Switches active focus to target_node_id.

        Traverses downward from target_node_id along the newest children
        to reach the subtree leaf, setting it as active_leaf_id.
        """
        if target_node_id not in self.nodes:
            raise KeyError(f"Target node '{target_node_id}' not found.")

        curr_id = target_node_id
        while self.nodes[curr_id].children_ids:
            # Pick latest child chronologically
            children = [self.nodes[cid] for cid in self.nodes[curr_id].children_ids if cid in self.nodes]
            if not children:
                break
            children.sort(key=lambda n: n.created_at, reverse=True)
            curr_id = children[0].node_id

        self.active_leaf_id = curr_id
        return self.get_linear_path(self.active_leaf_id)

    def get_navigator_meta(self, node_id: str) -> BranchNavigatorMeta | None:
        """Computes UI branch selector metadata (< current/total >) for a given node."""
        if node_id not in self.nodes:
            return None

        node = self.nodes[node_id]
        if node.parent_id is None:
            siblings = list(self.root_node_ids)
        else:
            parent = self.nodes.get(node.parent_id)
            siblings = list(parent.children_ids) if parent else [node_id]

        if not siblings:
            siblings = [node_id]

        try:
            idx = siblings.index(node_id) + 1
        except ValueError:
            idx = 1

        return BranchNavigatorMeta(
            node_id=node_id,
            branch_id=node.branch_id,
            branch_index=idx,
            total_branches=len(siblings),
            sibling_node_ids=siblings,
            has_children=len(node.children_ids) > 0,
        )

    def to_dict(self) -> dict[str, str | list[str] | dict[str, dict[str, str | int | float | bool | list[str] | dict[str, str | int | float | bool] | None]] | None]:
        """Serializes the entire DAG into a structured dictionary."""
        serialized_nodes: dict[str, dict[str, str | int | float | bool | list[str] | dict[str, str | int | float | bool] | None]] = {
            nid: n.to_dict() for nid, n in self.nodes.items()
        }
        return {
            "session_id": self.session_id,
            "root_node_ids": list(self.root_node_ids),
            "active_leaf_id": self.active_leaf_id,
            "nodes": serialized_nodes,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, str | list[str] | dict[str, Mapping[str, str | int | float | bool | list[str] | dict[str, str | int | float | bool] | None]] | None],
    ) -> SessionDagGraph:
        """Reconstructs SessionDagGraph from dictionary payload."""
        sess_id = str(data.get("session_id", ""))
        graph = cls(session_id=sess_id)

        raw_roots = data.get("root_node_ids")
        if isinstance(raw_roots, list):
            graph.root_node_ids = [str(r) for r in raw_roots]

        leaf_id = data.get("active_leaf_id")
        graph.active_leaf_id = str(leaf_id) if leaf_id is not None else None

        raw_nodes = data.get("nodes")
        if isinstance(raw_nodes, dict):
            for nid, node_payload in raw_nodes.items():
                if isinstance(node_payload, dict):
                    node = SessionDagNode.from_dict(node_payload)
                    graph.nodes[str(nid)] = node

        return graph
