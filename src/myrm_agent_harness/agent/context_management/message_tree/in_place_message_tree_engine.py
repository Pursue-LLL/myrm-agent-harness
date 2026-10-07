# ============================================================================
# In-Place Message Tree Branching & Version Navigator Engine (Item 164)
# True tree-structured message DAG, sibling version navigation (< 1/3 >),
# alternative branching, and instantaneous active timeline path resolution.
# ============================================================================

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from .message_tree_types import (
    MessageTreeGraph,
    SiblingVersionItem,
    TreeMessageNode,
    TreeNodeRole,
    VersionSwitchResult,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InPlaceMessageTreeEngine:
    """Manages in-place branching, sibling version switching, and path resolution."""

    def __init__(self) -> None:
        # session_id -> {node_id: TreeMessageNode}
        self._nodes: dict[str, dict[str, TreeMessageNode]] = {}
        # session_id -> {parent_id (or None): [child_node_id, ...]}
        self._children: dict[str, dict[str | None, list[str]]] = {}
        # session_id -> {parent_id (or None): selected_child_node_id}
        self._active_child_selection: dict[str, dict[str | None, str]] = {}
        # session_id -> root_node_id
        self._roots: dict[str, str] = {}

    def append_message(
        self,
        session_id: str,
        role: TreeNodeRole,
        content: str,
        parent_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> TreeMessageNode:
        """Append a message to the active path or under an explicit parent node."""
        session_nodes = self._nodes.setdefault(session_id, {})
        session_children = self._children.setdefault(session_id, {})
        session_selection = self._active_child_selection.setdefault(session_id, {})

        # If parent_id not specified, attach to current active leaf
        if parent_id is None and session_nodes:
            active_path = self._resolve_active_path_ids(session_id)
            if active_path:
                parent_id = active_path[-1]

        node_id = f"node-{uuid.uuid4().hex[:12]}"
        now_iso = _utc_now_iso()

        siblings = session_children.setdefault(parent_id, [])
        siblings.append(node_id)
        sibling_idx = len(siblings)
        total_siblings = len(siblings)

        new_node = TreeMessageNode(
            node_id=node_id,
            session_id=session_id,
            parent_id=parent_id,
            role=role,
            content=content,
            sibling_index=sibling_idx,
            total_siblings=total_siblings,
            child_ids=(),
            created_at_iso=now_iso,
            metadata=dict(metadata or {}),
        )
        session_nodes[node_id] = new_node

        # Update sibling total count on all prior siblings under the same parent
        self._sync_sibling_totals(session_id, parent_id, total_siblings)

        # Update parent's child_ids tuple
        if parent_id is not None and parent_id in session_nodes:
            p = session_nodes[parent_id]
            updated_parent = TreeMessageNode(
                node_id=p.node_id,
                session_id=p.session_id,
                parent_id=p.parent_id,
                role=p.role,
                content=p.content,
                sibling_index=p.sibling_index,
                total_siblings=p.total_siblings,
                child_ids=p.child_ids + (node_id,),
                created_at_iso=p.created_at_iso,
                metadata=p.metadata,
            )
            session_nodes[parent_id] = updated_parent

        # Select newly created node as active child of parent
        session_selection[parent_id] = node_id

        if parent_id is None and session_id not in self._roots:
            self._roots[session_id] = node_id

        logger.info(
            "Appended message '%s' in session '%s' (parent: %s, sibling: %d/%d)",
            node_id,
            session_id,
            parent_id,
            sibling_idx,
            total_siblings,
        )
        return session_nodes[node_id]

    def branch_alternative(
        self,
        session_id: str,
        sibling_node_id: str,
        role: TreeNodeRole,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> TreeMessageNode:
        """Branch an alternative response sharing the same parent as target node."""
        session_nodes = self._nodes.get(session_id)
        if not session_nodes or sibling_node_id not in session_nodes:
            raise KeyError(f"Node '{sibling_node_id}' not found in session '{session_id}'.")

        target_node = session_nodes[sibling_node_id]
        parent_id = target_node.parent_id

        return self.append_message(
            session_id=session_id,
            role=role,
            content=content,
            parent_id=parent_id,
            metadata=metadata,
        )

    def switch_sibling_version(
        self,
        session_id: str,
        node_id: str,
        target_sibling_index: int,
    ) -> VersionSwitchResult:
        """Switch active version among siblings (< 1/3 >) and refresh active path."""
        session_nodes = self._nodes.get(session_id)
        if not session_nodes or node_id not in session_nodes:
            raise KeyError(f"Node '{node_id}' not found in session '{session_id}'.")

        curr_node = session_nodes[node_id]
        parent_id = curr_node.parent_id
        siblings = self._children.get(session_id, {}).get(parent_id, [])

        if target_sibling_index < 1 or target_sibling_index > len(siblings):
            raise IndexError(
                f"Target sibling index {target_sibling_index} out of range [1, {len(siblings)}]."
            )

        target_selected_id = siblings[target_sibling_index - 1]
        self._active_child_selection.setdefault(session_id, {})[parent_id] = target_selected_id

        active_path_ids = self._resolve_active_path_ids(session_id)

        logger.info(
            "Switched sibling version on node '%s': %d -> %d (%s active)",
            node_id,
            curr_node.sibling_index,
            target_sibling_index,
            target_selected_id,
        )

        return VersionSwitchResult(
            session_id=session_id,
            target_node_id=target_selected_id,
            previous_sibling_index=curr_node.sibling_index,
            new_sibling_index=target_sibling_index,
            total_siblings=len(siblings),
            active_path_node_ids=active_path_ids,
        )

    def get_sibling_versions(
        self,
        session_id: str,
        node_id: str,
    ) -> tuple[SiblingVersionItem, ...]:
        """Get summary items of all sibling variants for < 1/3 > in-place navigator."""
        session_nodes = self._nodes.get(session_id, {})
        curr_node = session_nodes.get(node_id)
        if curr_node is None:
            raise KeyError(f"Node '{node_id}' not found in session '{session_id}'.")

        parent_id = curr_node.parent_id
        siblings = self._children.get(session_id, {}).get(parent_id, [])
        active_id = self._active_child_selection.get(session_id, {}).get(parent_id)

        items: list[SiblingVersionItem] = []
        for idx, sid in enumerate(siblings, start=1):
            s_node = session_nodes[sid]
            preview = s_node.content[:60] + "..." if len(s_node.content) > 60 else s_node.content
            items.append(
                SiblingVersionItem(
                    node_id=s_node.node_id,
                    sibling_index=idx,
                    content_preview=preview,
                    created_at_iso=s_node.created_at_iso,
                    is_active=(sid == active_id),
                )
            )
        return tuple(items)

    def get_active_timeline_messages(
        self,
        session_id: str,
    ) -> tuple[TreeMessageNode, ...]:
        """Resolve linear active path from root to current selected leaf."""
        active_ids = self._resolve_active_path_ids(session_id)
        session_nodes = self._nodes.get(session_id, {})
        return tuple(session_nodes[nid] for nid in active_ids if nid in session_nodes)

    def get_message_tree_graph(self, session_id: str) -> MessageTreeGraph:
        """Construct complete message DAG representation of session."""
        session_nodes = self._nodes.get(session_id, {})
        root_id = self._roots.get(session_id)
        active_path = self._resolve_active_path_ids(session_id)
        active_leaf = active_path[-1] if active_path else None

        return MessageTreeGraph(
            session_id=session_id,
            root_node_id=root_id,
            nodes=tuple(session_nodes.values()),
            active_leaf_id=active_leaf,
            active_path_ids=active_path,
        )

    def _sync_sibling_totals(
        self,
        session_id: str,
        parent_id: str | None,
        total_siblings: int,
    ) -> None:
        """Sync total_siblings on all nodes sharing the same parent."""
        session_nodes = self._nodes.get(session_id, {})
        siblings = self._children.get(session_id, {}).get(parent_id, [])
        for sid in siblings:
            node = session_nodes.get(sid)
            if node is not None and node.total_siblings != total_siblings:
                session_nodes[sid] = TreeMessageNode(
                    node_id=node.node_id,
                    session_id=node.session_id,
                    parent_id=node.parent_id,
                    role=node.role,
                    content=node.content,
                    sibling_index=node.sibling_index,
                    total_siblings=total_siblings,
                    child_ids=node.child_ids,
                    created_at_iso=node.created_at_iso,
                    metadata=node.metadata,
                )

    def _resolve_active_path_ids(self, session_id: str) -> tuple[str, ...]:
        """Traverse tree following selected child pointers from root to leaf."""
        session_nodes = self._nodes.get(session_id)
        if not session_nodes:
            return ()

        root_id = self._roots.get(session_id)
        if not root_id:
            return ()

        path: list[str] = []
        curr_id: str | None = root_id
        visited: set[str] = set()

        while curr_id is not None and curr_id in session_nodes:
            if curr_id in visited:
                break
            visited.add(curr_id)
            path.append(curr_id)

            # Move to active selected child of curr_id
            curr_id = self._active_child_selection.get(session_id, {}).get(curr_id)

        return tuple(path)
